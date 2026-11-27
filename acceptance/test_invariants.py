"""Invariants every finished job must satisfy (receipt, destroy, containment, secrecy)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import httpx
import pytest
from conftest import (
    JOB_TIMEOUT,
    REGISTRY,
    SCENARIOS,
    TERMINAL,
    Scenario,
    evidence_unavailable,
    finding_code,
    findings,
    post_job,
    snapshot,
    submit,
    wait_terminal,
)
from evidence import (
    HostEvidenceError,
    check_generations,
    check_observed_transitions,
    check_receipt_before_terminal,
    check_resume,
    check_stitched_stream,
    event_ids,
    parse_sse,
    replaced_lifecycle_events,
    validate_operator_evidence,
    verify_host_cleanup,
)

pytestmark = pytest.mark.slow
_IDS = [s.name for s in SCENARIOS]
_SHA = re.compile(r"^[0-9a-f]{40}$")
# Shape of Killhub's planted fake AWS key canary: must never be served.
_CANARY_KEY = re.compile(r"CKEY_[0-9a-f]{40}")


def _replay(client, job_id: str, **params) -> list[dict]:
    """Persisted event replay of a (terminal) job, parsed."""
    r = client.get(f"/api/jobs/{job_id}/events", params=params or None, timeout=60)
    assert r.status_code == 200, (job_id, r.status_code, r.text[:200])
    return parse_sse(r.text)


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_receipt_written_before_terminal(client, scenario_run, sc: Scenario) -> None:
    snap = scenario_run.results[sc.name]
    receipt = snap.get("receipt") or {}
    assert receipt.get("verification") is not None or sc.status == "failed", receipt
    assert receipt.get("dossier"), receipt.keys()
    assert receipt["dossier"].get("outcome") in {sc.status, None} or sc.status in json.dumps(
        receipt["dossier"]
    )
    # Ordering from persisted events: terminal status event cannot predate the receipt.
    events = _replay(client, scenario_run.job_ids[sc.name])
    assert not check_receipt_before_terminal(snap, events), check_receipt_before_terminal(
        snap, events
    )


def test_no_terminal_status_observed_without_receipt() -> None:
    """Every poll this session made (scenarios, cancels, SSE job) respects D61."""
    assert REGISTRY.observations, "no polled snapshots recorded"
    assert not check_observed_transitions(REGISTRY.observations)


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_sandbox_destroyed_and_confirmed(scenario_run, sc: Scenario) -> None:
    snap = scenario_run.results[sc.name]
    if not snap.get("sandbox_id"):
        pytest.skip("no sandbox was created")
    assert (snap.get("cleanup") or {}).get("status") == "destroyed", snap.get("cleanup")
    assert snap.get("destroyed_at"), "destroyed_at missing after confirmed removal"
    assert snap["destroyed_at"] <= snap["expires_at"], (snap["destroyed_at"], snap["expires_at"])


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_source_commit_pinned(scenario_run, sc: Scenario) -> None:
    snap = scenario_run.results[sc.name]
    if snap.get("sandbox_id"):
        assert _SHA.match(str(snap.get("resolved_commit") or "")), snap.get("resolved_commit")


@pytest.mark.parametrize("sc", [s for s in SCENARIOS if s.readiness], ids=lambda s: s.name)
def test_containment_evidence_present(scenario_run, sc: Scenario) -> None:
    snap = scenario_run.results[sc.name]
    containment = (snap.get("receipt") or {}).get("containment") or {}
    assert containment.get("claim") in {"proven", "incomplete"}, containment.get("claim")
    dims = containment.get("dimensions") or {}
    for dim in (
        "timeout_enforcement",
        "host_access_denied",
        "sibling_access_denied",
        "host_liveness",
    ):
        assert dim in dims, (dim, sorted(dims))
    codes = {finding_code(f) for f in findings(snap) if f.get("source") == "network"}
    assert "cp_denied_install" in codes, codes  # control plane unreachable during install
    assert "offline_denied" in codes, codes  # deny-all egress after install


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_vuln_report_present(scenario_run, sc: Scenario) -> None:
    report = scenario_run.results[sc.name].get("vuln_report") or {}
    assert report.get("status") in {"ok", "partial", "failed"}, report.get("status")
    for f in report.get("findings") or []:
        assert f.get("id") and f.get("severity") and f.get("source"), f


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_no_canary_or_secret_served(client, scenario_run, sc: Scenario) -> None:
    jid = scenario_run.job_ids[sc.name]
    texts = [
        client.get(f"/api/jobs/{jid}").text,
        client.get(f"/api/jobs/{jid}/events", timeout=60).text,
    ]
    for text in texts:
        assert not _CANARY_KEY.search(text), "fake canary key served"
        for name in ("VULTR_API_KEY", "VULTR_INFERENCE_API_KEY", "INTERNAL_API_TOKEN"):
            assert f"{name}=" not in text


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_poll_and_stream_agree_on_terminal_status(client, scenario_run, sc: Scenario) -> None:
    jid = scenario_run.job_ids[sc.name]
    final = None
    with client.stream("GET", f"/api/jobs/{jid}/events", timeout=60) as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
        for line in r.iter_lines():
            if line.startswith("data:"):
                try:
                    event = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "status" and event.get("status"):
                    final = event["status"]
    assert final == scenario_run.results[sc.name]["status"], (
        final,
        scenario_run.results[sc.name]["status"],
    )


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_stream_resumes_after_cursor(client, scenario_run, sc: Scenario) -> None:
    jid = scenario_run.job_ids[sc.name]
    snap = client.get(f"/api/jobs/{jid}").json()
    cursor = snap.get("event_cursor")
    assert cursor, "snapshot must carry event_cursor"
    r = client.get(f"/api/jobs/{jid}/events", params={"after": cursor}, timeout=60)
    assert r.status_code in (200, 410)
    ids = [int(x) for x in re.findall(r"^id: (\d+)$", r.text, re.M)]
    assert all(i > int(cursor) for i in ids), (cursor, ids[:5])


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_stream_resume_from_mid_cursor_is_exact(client, scenario_run, sc: Scenario) -> None:
    """Reconnect from a cursor with later events: exactly the later events, once each."""
    jid = scenario_run.job_ids[sc.name]
    full = event_ids(_replay(client, jid))
    assert len(full) >= 4, f"too few events to pick a mid cursor: {full}"
    cursor = full[len(full) // 2]
    assert any(i > cursor for i in full), "mid cursor has no later events"
    for use_header in (False, True):  # ?after= and Last-Event-ID must behave the same
        if use_header:
            r = client.get(
                f"/api/jobs/{jid}/events", headers={"Last-Event-ID": str(cursor)}, timeout=60
            )
        else:
            r = client.get(f"/api/jobs/{jid}/events", params={"after": cursor}, timeout=60)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        problems = check_resume(full, event_ids(parse_sse(r.text)), cursor)
        assert not problems, problems


def _read_events(
    client, job_id: str, *, after: int | None, stop_after: int | None, deadline: float
):
    """Read one SSE connection: (events, saw_terminal); closes early at ``stop_after``."""
    headers = {"Last-Event-ID": str(after)} if after is not None else {}
    events: list[dict] = []
    saw_terminal = False
    cur: dict = {}
    timeout = httpx.Timeout(30.0, read=90.0)
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=headers, timeout=timeout) as r:
        assert r.status_code == 200, r.status_code
        for line in r.iter_lines():
            if time.monotonic() > deadline:
                break
            if line.startswith("id:"):
                cur = {"id": line[3:].strip()}
            elif line.startswith("event:"):
                cur["type"] = line[6:].strip()
            elif line.startswith("data:"):
                try:
                    cur["data"] = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    cur["data"] = None
            elif line == "" and cur.get("id") is not None:
                events.append(cur)
                data = cur.get("data") or {}
                if cur.get("type") == "status" and data.get("status") in TERMINAL:
                    saw_terminal = True
                cur = {}
                if stop_after is not None and len(events) >= stop_after:
                    break
    return events, saw_terminal


def test_sse_reconnect_mid_run_loses_and_duplicates_nothing(client) -> None:
    """Drop a live stream mid-run, resume from its cursor, compare with the final replay."""
    jid = submit(
        client, "https://github.com/mokafari/killhub-sca-npm-control-20261127", "sse_reconnect"
    )
    deadline = time.monotonic() + JOB_TIMEOUT
    first, done = _read_events(client, jid, after=None, stop_after=3, deadline=deadline)
    assert not done, "job finished before the stream could be cut mid-run"
    assert len(first) == 3, f"expected 3 events before the cut, got {len(first)}"
    before = event_ids(first)
    resumed_ids: list[int] = []
    cursor = before[-1]
    for _ in range(20):  # a proxy may also cut the tail; keep resuming from the last id
        part, done = _read_events(client, jid, after=cursor, stop_after=None, deadline=deadline)
        part_ids = event_ids(part)
        assert not check_resume(part_ids, part_ids, cursor), part_ids[:10]
        resumed_ids += part_ids
        if part_ids:
            cursor = part_ids[-1]
        if done or time.monotonic() > deadline:
            break
    assert resumed_ids, "no events after the mid-run cursor"
    final = wait_terminal(client, {"sse": jid}, timeout=600)["sse"]
    assert final["status"] in TERMINAL
    full = event_ids(_replay(client, jid))
    problems = check_stitched_stream(before, resumed_ids, full)
    assert not problems, problems


@pytest.mark.release
@pytest.mark.host_cleanup
def test_no_sandboxes_left_running_on_host(scenario_run) -> None:
    """Independent host evidence: SSH must succeed, inventory must parse, no job VM remains.

    Covers scenario jobs, cancel and cancel-boundary jobs, the SSE job, every
    recorded sandbox generation and containment sibling probe VMs (kh-sib-*).
    Unavailable evidence is a failure under KILLHUB_RELEASE=1 (skip otherwise).
    """
    host = os.environ.get("KILLHUB_SSH_HOST")
    if not host:
        evidence_unavailable("set KILLHUB_SSH_HOST to collect host cleanup evidence")
    job_ids = REGISTRY.job_ids
    not_terminal = [
        j for j in job_ids if (REGISTRY.snapshots.get(j) or {}).get("status") not in TERMINAL
    ]
    assert not not_terminal, f"jobs not terminal, host check would be premature: {not_terminal}"
    command = os.environ.get("KILLHUB_INVENTORY_COMMAND")
    kwargs = {"command": command} if command else {}
    try:
        REGISTRY.host_evidence = verify_host_cleanup(host, job_ids, REGISTRY.snapshots, **kwargs)
    except HostEvidenceError as exc:
        REGISTRY.host_evidence = exc.evidence  # retained in the artifact bundle either way
        raise


def test_image_replacement_keeps_one_vm_and_records_generations(client, scenario_run) -> None:
    """D27/D36: replaced generations are closed out; the receipt and stream agree."""
    replaced = {
        name: snap
        for name, snap in scenario_run.results.items()
        if len(((snap.get("receipt") or {}).get("dossier") or {}).get("sandbox_generations") or [])
        > 1
    }
    if not replaced:
        evidence_unavailable("no scenario replaced its sandbox image, replacement unproven")
    for name, snap in replaced.items():
        gens = snap["receipt"]["dossier"]["sandbox_generations"]
        destroyed = (snap.get("cleanup") or {}).get("status") == "destroyed"
        assert not check_generations(gens, destroyed=destroyed), (name, gens)
        events = _replay(client, scenario_run.job_ids[name])
        assert replaced_lifecycle_events(events) == list(range(2, len(gens) + 1)), (name, gens)


def test_admission_capacity_released_after_jobs_finish(client, scenario_run) -> None:
    """All earlier jobs are terminal, so a new create must be admitted, not queue_full.

    A leaked running/queued slot (finalize or cancel not releasing admission, D40/D71)
    would eventually answer 503 queue_full even though nothing is running.
    """
    non_terminal = [
        j
        for j in REGISTRY.job_ids
        if (REGISTRY.snapshots.get(j) or {}).get("status") not in TERMINAL
    ]
    assert not non_terminal, non_terminal
    cheap = next(sc for sc in SCENARIOS if sc.name == "setup_failed")
    r = post_job(client, {"git_url": cheap.url}, budget=120)
    assert r.status_code in (200, 201), (
        f"create refused with capacity that should be free: {r.status_code} {r.text[:200]}"
    )
    jid = r.json()["job_id"]
    REGISTRY.register("admission_probe", jid)
    snapshot(client, jid)
    client.delete(f"/api/jobs/{jid}")
    final = wait_terminal(client, {"admission_probe": jid}, timeout=900)["admission_probe"]
    assert final["status"] in TERMINAL


@pytest.mark.release
def test_operator_gated_evidence_present() -> None:
    """Restart recovery and host expiry with the CP stopped need an operator (README).

    Release validation requires KILLHUB_OPERATOR_EVIDENCE to point at the operator's
    JSON evidence file; it is validated and retained with the artifacts.
    """
    path = os.environ.get("KILLHUB_OPERATOR_EVIDENCE")
    if not path:
        evidence_unavailable(
            "operator-gated scenarios (restart recovery, host expiry with CP stopped) "
            "have no KILLHUB_OPERATOR_EVIDENCE file"
        )
    doc = json.loads(Path(path).read_text())
    REGISTRY.notes["operator_evidence"] = doc
    assert not validate_operator_evidence(doc), validate_operator_evidence(doc)
