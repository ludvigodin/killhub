"""Invariants every finished job must satisfy (receipt, destroy, containment, secrecy)."""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest
from conftest import SCENARIOS, Scenario, finding_code, findings

pytestmark = pytest.mark.slow
_IDS = [s.name for s in SCENARIOS]
_SHA = re.compile(r"^[0-9a-f]{40}$")
# Shape of Killhub's planted fake AWS key canary: must never be served.
_CANARY_KEY = re.compile(r"CKEY_[0-9a-f]{40}")


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_receipt_written_before_terminal(scenario_run, sc: Scenario) -> None:
    receipt = scenario_run.results[sc.name].get("receipt") or {}
    assert receipt.get("verification") is not None or sc.status == "failed", receipt
    assert receipt.get("dossier"), receipt.keys()
    assert receipt["dossier"].get("outcome") in {sc.status, None} or sc.status in json.dumps(
        receipt["dossier"]
    )


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


def test_no_sandboxes_left_running_on_host(scenario_run) -> None:
    host = os.environ.get("KILLHUB_SSH_HOST")
    if not host:
        pytest.skip("set KILLHUB_SSH_HOST to check the sandbox host")
    ours = {f"kh-{jid}" for jid in scenario_run.job_ids.values()}
    out = subprocess.run(
        ["ssh", host, "/opt/killhub-msb/bin/killhub-msb list 2>/dev/null || msb list"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    leaked = [name for name in ours if name in out]
    assert not leaked, leaked
