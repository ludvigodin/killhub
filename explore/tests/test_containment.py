"""Containment matrix + canary scan (D58, D65, D44)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from canaries import generate_canaries, persist_canaries, scan_canaries
from config import get_settings
from containment import (
    compute_claim,
    probe_host_access_denied,
    probe_timeout_enforcement,
    run_containment_probes,
)
from errors import HarnessError
from harness import CliResult, ExecResult
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("CONTAINMENT_ON_CLAIM", "false")
    monkeypatch.setenv("CANARY_STORAGE", str(tmp_path / "canaries"))
    monkeypatch.setenv("CONTROL_PLANE_PROBE_URL", "https://example.com")
    monkeypatch.setenv("CONTROL_PLANE_DENY_HOSTS", "example.com")
    monkeypatch.setenv("MSB_HOST", "root@203.0.113.50")
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _seed_job() -> str:
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-contain",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    cans = generate_canaries(job.job_id)
    persist_canaries(cans)
    # Retain install-phase CP deny evidence on the stream.
    ledger.append_event(
        job.job_id,
        typ="log",
        message="install CP probe → policy_denied",
        payload={
            "kind": "network_probe",
            "phase": "install",
            "probe_session": "install_cp_deny",
            "classification": "policy_denied",
            "reason": "guest_denied_cp_while_egress_works",
            "target": "https://example.com",
            "host_ok": True,
            "egress_class": "ok",
        },
    )
    return job.job_id


def test_compute_claim_requires_all_dimensions() -> None:
    dims = {
        "timeout_enforcement": {"dimension": "timeout_enforcement", "ok": True},
        "host_access_denied": {
            "dimension": "host_access_denied",
            "ok": True,
            "classification": "policy_denied",
        },
        "sibling_access_denied": {
            "dimension": "sibling_access_denied",
            "ok": True,
            "classification": "policy_denied",
        },
        "host_liveness": {"dimension": "host_liveness", "ok": True},
    }
    assert compute_claim(dims) == "proven"
    dims["sibling_access_denied"]["classification"] = "inconclusive"
    dims["sibling_access_denied"]["ok"] = False
    assert compute_claim(dims) == "incomplete"


def test_timeout_enforcement_records_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job()
    calls: list[str] = []

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        calls.append(joined)
        if "while true" in joined:
            raise HarnessError("msb timed out: exec", code="msb_timeout")
        return ExecResult("alive\n", "", 0)

    monkeypatch.setattr("containment.exec_command", _exec)
    evidence = probe_timeout_enforcement("env-contain", job_id=job_id, settings=get_settings())
    assert evidence["ok"] is True
    assert evidence["timed_out"] is True
    assert evidence["classification"] == "policy_denied"
    assert evidence["absorption"]["absorbed"] is True
    assert evidence["absorption"]["kind"] == "infinite_loop"
    events = get_ledger().list_events(job_id)
    assert any(e.type == "containment" for e in events)
    assert any("ABSORBED" in (e.message or "") for e in events)


def test_canary_scan_flags_unexpected_path(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job()
    stored = __import__("canaries", fromlist=["load_canaries"]).load_canaries(job_id)

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "deliberate" in joined:
            return ExecResult("deliberate_ok\n", "", 0)
        if "KILLHUB_CANARY_SCAN" in joined or "python3" in joined:
            return ExecResult(
                '{"hits": ["/tmp/exfil/stolen.txt"], "scanned": true}\n',
                "",
                0,
            )
        return ExecResult("", "", 0)

    # scan_canaries does a local `from harness import exec_command`.
    monkeypatch.setattr("harness.exec_command", _exec)
    result = scan_canaries("env-contain", job_id=job_id, settings=get_settings())
    assert result["hit_count"] == 1
    assert "/tmp/exfil/stolen.txt" in result["unexpected_hits"]
    findings = [e for e in get_ledger().list_events(job_id) if e.type == "finding"]
    assert any(e.payload.get("source") == "canary" for e in findings)
    assert stored is not None
    for e in findings:
        blob = str(e.payload)
        for secret in stored.env.values():
            assert secret not in blob


def test_run_containment_matrix_proven_with_scorable_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_job()

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "while true" in joined:
            raise HarnessError("msb timed out: exec", code="msb_timeout")
        if "host_liveness_guest_ok" in joined or "alive" in joined:
            return ExecResult("host_liveness_guest_ok\nalive\n", "", 0)
        if "true" == joined.strip() or joined.endswith("true"):
            return ExecResult("", "", 0)
        if "apt-get" in joined or "tools_ok" in joined:
            return ExecResult("tools_ok\n", "", 0)
        if "http.server" in joined:
            return ExecResult("1234\n", "", 0)
        if "172.16.0.99:8080" in joined:
            return ExecResult("ok\n", "", 0)
        if "tooling_missing" in joined:
            return ExecResult("tooling_missing\n", "", 3)
        if "network_probe" in joined or "wget" in joined or "curl" in joined:
            return ExecResult("fail\n", "", 1)
        if "deliberate" in joined:
            return ExecResult("deliberate_ok\n", "", 0)
        if "KILLHUB_CANARY_SCAN" in joined or "python3" in joined:
            return ExecResult('{"hits": [], "scanned": true}\n', "", 0)
        if "hostname -I" in joined:
            return ExecResult("172.16.0.99\n", "", 0)
        return ExecResult("", "", 0)

    monkeypatch.setattr("containment.exec_command", _exec)
    monkeypatch.setattr("harness.exec_command", _exec)
    monkeypatch.setattr("containment._host_fetch_ok", lambda url, timeout=5.0: (True, "http_200"))
    monkeypatch.setattr(
        "containment.list_live_environment_ids",
        lambda **k: {"env-contain"},
    )

    monkeypatch.setattr("containment._tcp_positive_control", lambda url: (url, "connected"))

    # Sibling create/remove via fake CLI.
    cli = MagicMock()
    cli.remove.return_value = CliResult((), 0, "", "")
    cli.create.return_value = CliResult((), 0, "", "")
    cli.stop.return_value = CliResult((), 0, "", "")
    monkeypatch.setattr("containment.wait_until_ready", lambda *a, **k: None)

    # Guest fetch helper path used by host/sibling probes.
    def _guest_fetch(environment_id, url, **kwargs):
        return "denied", 1, "denied"

    monkeypatch.setattr("containment._guest_fetch", _guest_fetch)
    monkeypatch.setattr(
        "containment._guest_ipv4",
        lambda *a, **k: "172.16.0.99",
    )

    # Sibling local positive control via exec_command already returns 0 for wget/curl.

    result = run_containment_probes(job_id, settings=get_settings(), cli=cli)
    # Guest-network probes stay inconclusive (no Plane-1 positive control) but must
    # not veto a solid CP/management deny matrix (D65 scorable-only scoring).
    assert result.claim == "proven"
    probes = result.dimensions["host_access_denied"]["probes"]
    guest_only = [p for p in probes if p["name"] in {"host_internal", "host_gateway_ip"}]
    assert len(guest_only) == 2
    assert all(
        p["classification"] == "inconclusive" and p["checked_peer"] is None for p in guest_only
    )
    assert all(p.get("scorable") is False for p in guest_only)
    assert result.dimensions["host_access_denied"]["ok"] is True
    assert result.dimensions["timeout_enforcement"]["absorption"]["absorbed"] is True
    assert set(result.dimensions) == {
        "timeout_enforcement",
        "host_access_denied",
        "sibling_access_denied",
        "host_liveness",
    }
    assert result.dimensions["sibling_access_denied"]["classification"] == "policy_denied"
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status != "completed"
    assert job.destroyed_at is None
    receipt = get_ledger().get_receipt(job_id)
    assert receipt is not None
    assert receipt["containment"]["claim"] == result.claim
    events = get_ledger().list_events(job_id)
    assert any(e.type == "containment" for e in events)
    assert any("ABSORBED" in (e.message or "") for e in events)


def test_guest_network_probes_do_not_block_host_deny_proof(monkeypatch):
    """host_internal / gateway stay inconclusive; scorable CP denials still prove."""
    job_id = _seed_job()
    monkeypatch.setattr(
        "containment._tcp_positive_control",
        lambda url: (url if url.startswith("https:") else None, "control"),
    )
    monkeypatch.setattr("containment._guest_fetch", lambda *a, **k: ("denied", 0, "unreachable"))
    result = probe_host_access_denied(
        "env-contain",
        job_id=job_id,
        settings=get_settings(),
        install_cp={"classification": "policy_denied"},
    )
    assert result["classification"] == "policy_denied"
    assert result["ok"] is True
    assert any(p["classification"] == "policy_denied" for p in result["probes"])
    assert any(
        p["name"] in {"host_internal", "host_gateway_ip"} and p["classification"] == "inconclusive"
        for p in result["probes"]
    )


def test_missing_control_plane_positive_control_prevents_proof(monkeypatch):
    job_id = _seed_job()
    monkeypatch.setattr(
        "containment._tcp_positive_control",
        lambda url: (None, "unreachable"),
    )
    monkeypatch.setattr("containment._guest_fetch", lambda *a, **k: ("denied", 0, "unreachable"))
    result = probe_host_access_denied(
        "env-contain",
        job_id=job_id,
        settings=get_settings(),
        install_cp={"classification": "policy_denied"},
    )
    assert result["classification"] == "inconclusive"
    assert not result["ok"]
    assert any(p["classification"] == "policy_denied" for p in result["probes"])


def test_gateway_control_never_dials_default_interface(monkeypatch):
    from containment import _gateway_control

    monkeypatch.setattr(
        "containment.Path.read_text", lambda path: "Iface Destination\neth0 00000000"
    )
    with_socket = MagicMock()
    monkeypatch.setattr("containment.socket.socket", with_socket)
    assert _gateway_control("eth0") == (None, "dedicated_guest_interface_required")
    with_socket.assert_not_called()
