"""Finalize: receipt before terminal + destroy confirm + gates (D49, D57, D66)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from config import get_settings
from finalize import evaluate_gates, finalize_job
from harness import DestroyResult
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job
from vulnscan import VulnScanResult


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("FINALIZE_ON_CLAIM", "false")
    monkeypatch.setenv("ARTIFACT_STORAGE", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _seed(
    *,
    readiness_passed: bool = True,
    verification_kind: str = "original_application",
    with_sandbox: bool = True,
) -> str:
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger()
    if with_sandbox:
        ledger.append_sandbox_generation(
            job.job_id,
            environment_id="env-final",
            image="debian",
            expires_at=job.expires_at,
            state="running",
        )
    ledger.update_job_fields(
        job.job_id,
        # Keep non-terminal so finalize owns the terminal transition.
        status="verifying",
        readiness={
            "passed": readiness_passed,
            "probe": "http-root",
            "detail": {"ok": readiness_passed},
        },
        verification={"kind": verification_kind},
        progress=90,
    )
    return job.job_id


def test_gates_fail_without_readiness() -> None:
    job_id = _seed(readiness_passed=False, verification_kind="setup_failed")
    gates = evaluate_gates(job_id, settings=get_settings())
    assert gates["terminal"] == "failed"
    assert gates["readiness_passed"] is False


def test_gates_complete_with_sca_findings_only() -> None:
    job_id = _seed(readiness_passed=True)
    ledger = get_ledger()
    ledger.append_event(
        job_id,
        typ="finding",
        message="dep advisory",
        payload={
            "source": "sca",
            "finding": {
                "id": "sca-abc",
                "severity": "medium",
                "title": "advisory",
                "source": "sca",
            },
        },
    )
    gates = evaluate_gates(job_id, settings=get_settings())
    assert gates["terminal"] == "completed"


def test_finalize_receipt_before_terminal_and_keeps_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed(readiness_passed=True)

    def fake_scan(job_id: str, **kwargs: Any) -> VulnScanResult:
        ledger = get_ledger()
        findings = [
            {
                "id": "sca-1",
                "severity": "low",
                "title": "test finding",
                "source": "sca",
            }
        ]
        ledger.upsert_vuln_report(
            job_id,
            summary="Cite-checked review — low: test finding [sca-1]",
            findings=findings,
            status="ok",
            mcp_assessment={"check": "filesystem_read_v1", "status": "partial"},
        )
        ledger.append_event(
            job_id,
            typ="finding",
            message="test finding",
            payload={"source": "sca", "finding": findings[0]},
        )
        return VulnScanResult(job_id=job_id, status="ok", findings=findings)

    monkeypatch.setattr("finalize.run_vuln_scan", fake_scan)
    monkeypatch.setattr(
        "finalize.destroy_job_environment",
        lambda *a, **k: DestroyResult(confirmed=True, error=None),
    )

    result = finalize_job(job_id, settings=get_settings())
    assert result.terminal_status == "completed"
    assert result.destroyed is True
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status == "completed"
    assert job.readiness is not None
    assert job.readiness.get("passed") is True
    assert job.destroyed_at is not None
    receipt = get_ledger().get_receipt(job_id)
    assert receipt is not None
    assert receipt["dossier"]["outcome"] == "completed"
    assert receipt["dossier"]["mcp_assessment"]["status"] == "partial"
    assert get_ledger().get_vuln_report(job_id) is not None

    # Receipt event ordering: receipt row exists; terminal status is completed.
    events = get_ledger().list_events(job_id)
    status_events = [e for e in events if e.type == "status"]
    assert status_events[-1].message == "completed"


def test_finalize_destroy_failed_still_terminals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed(readiness_passed=True)
    monkeypatch.setattr(
        "finalize.run_vuln_scan",
        lambda *a, **k: VulnScanResult(job_id=job_id, status="ok", findings=[]),
    )
    monkeypatch.setattr(
        "finalize.destroy_job_environment",
        lambda *a, **k: DestroyResult(confirmed=False, error="msb remove failed"),
    )
    # Still need vuln report row for dossier
    get_ledger().upsert_vuln_report(job_id, summary="clean", findings=[], status="ok")

    result = finalize_job(job_id, settings=get_settings())
    assert result.terminal_status == "completed"
    assert result.destroy_failed is True
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.destroyed_at is None
    assert job.cleanup.status == "destroy_failed"
    receipt = get_ledger().get_receipt(job_id)
    assert receipt is not None
    assert receipt["lifecycle"]["cleanup"] == "destroy_failed"


def test_finalize_setup_failed_path(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed(
        readiness_passed=False,
        verification_kind="setup_failed",
        with_sandbox=False,
    )
    monkeypatch.setattr(
        "finalize.run_vuln_scan",
        lambda *a, **k: VulnScanResult(job_id=job_id, status="ok", findings=[]),
    )
    destroy = MagicMock(return_value=DestroyResult(confirmed=True, error=None))
    monkeypatch.setattr("finalize.destroy_job_environment", destroy)
    get_ledger().upsert_vuln_report(job_id, summary="clean", findings=[], status="ok")

    result = finalize_job(job_id, settings=get_settings())
    assert result.terminal_status == "failed"
    # No sandbox → destroy_job_environment not required
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status == "failed"
    assert get_ledger().get_receipt(job_id) is not None


def test_finalize_reclaims_when_already_terminal_but_sandbox_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discover used to flip failed before destroy; finalize must still reclaim."""
    job_id = _seed(readiness_passed=False, verification_kind="setup_failed")
    ledger = get_ledger()
    # Terminal + receipt without destroy (D61); sandbox still live for reclaim.
    ledger.finalize_job(
        job_id,
        status="failed",
        receipt={
            "verification": {"kind": "setup_failed"},
            "dossier": {"outcome": "setup_failed", "reason": "forbid_demo"},
        },
        progress=100,
        current_step="setup_failed (fixture)",
        error="forbid_demo",
    )
    monkeypatch.setattr(
        "finalize.run_vuln_scan",
        lambda *a, **k: VulnScanResult(job_id=job_id, status="ok", findings=[]),
    )
    destroy = MagicMock(return_value=DestroyResult(confirmed=True, error=None))
    monkeypatch.setattr("finalize.destroy_job_environment", destroy)

    result = finalize_job(job_id, settings=get_settings())
    assert result.destroyed is True
    destroy.assert_called_once()
    job = ledger.get_job(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.destroyed_at is not None
    assert ledger.get_receipt(job_id) is not None


def test_active_checks_reach_card_and_agent(monkeypatch):
    from operator_mcp_tools import summarize_receipt
    from service import list_job_summaries

    job_id = _seed(with_sandbox=False)
    ledger = get_ledger()
    monkeypatch.setenv("ENABLE_VULN_REVIEW_LLM", "false")
    get_settings.cache_clear()
    for i in range(12):
        ledger.append_event(
            job_id,
            typ="finding",
            message="Routine observation",
            payload={"source": "network", "severity": "info", "code": f"info-{i}"},
        )
    for code, source, severity in [
        ("persistence_write", "activity", "high"),
        ("install_network_tools", "activity", "low"),
        ("mcp_tool_poisoning", "mcp_tool_review", "high"),
        ("mcp_tool_poisoning", "mcp_tool_review", "medium"),
        ("canary_exfiltration", "activity", "critical"),
    ]:
        ledger.append_event(
            job_id,
            typ="finding",
            message=code,
            payload={
                "source": source,
                "code": code,
                "severity": severity,
                "excerpt": "untrusted text",
            },
        )
    ledger.append_event(
        job_id,
        typ="log",
        message="Trace",
        payload={"kind": "install_activity", "coverage": "partial"},
    )
    ledger.append_event(
        job_id, typ="log", message="Review", payload={"kind": "mcp_tool_review", "tool_count": 3}
    )
    monkeypatch.setattr(
        "finalize.destroy_job_environment",
        lambda *a, **k: DestroyResult(confirmed=True, error=None),
    )
    finalize_job(job_id, settings=get_settings())
    snapshot = ledger.get_snapshot(job_id)
    agent = summarize_receipt(snapshot, base_url="https://example.test")
    card = list_job_summaries()[0]
    checks = card["active_checks"]
    assert checks == agent["active_checks"] == snapshot["receipt"]["dossier"]["active_checks"]
    assert checks["install_trace"] == "partial" and checks["mcp_tools_reviewed"] == 3
    assert checks["finding_count"] == 5 and checks["leading_finding"]["severity"] == "critical"
    assert agent["findings"][0]["id"] == checks["leading_finding"]["id"]
    assert {row["check"]: row["count"] for row in checks["by_check"]} == {
        "canary_exfiltration": 1,
        "persistence_write": 1,
        "install_network_tools": 1,
        "mcp_tool_poisoning": 2,
    }
    for row in checks["by_check"]:
        assert f"[{row['finding_id']}]" in agent["vuln_review"]
    assert agent["finding_count"] == 17 and len(agent["findings"]) == 10
    assert agent["scan_status"] == "partial"
    assert agent["vuln_review"] == snapshot["vuln_report"]["summary"]
    assert len({f["id"] for f in agent["findings"] if f["source"] == "mcp_tool_review"}) == 2
    assert "untrusted text" not in str(snapshot["vuln_report"])


def test_historical_report_uses_retained_evidence_without_rewriting_receipt():
    from operator_mcp_tools import summarize_receipt
    from service import list_job_summaries

    job_id = _seed(with_sandbox=False)
    ledger = get_ledger()
    ledger.append_event(
        job_id,
        typ="log",
        message="Install trace",
        payload={"kind": "install_activity", "coverage": "full", "trace_bytes": 0},
    )
    ledger.append_event(
        job_id,
        typ="finding",
        message="Install ran a network tool",
        payload={"source": "activity", "code": "install_network_tools", "severity": "low"},
    )
    ledger.upsert_vuln_report(
        job_id,
        findings=[],
        status="ok",
        summary="No scan findings. Clean bill for this job's scanned surfaces.",
    )
    ledger.upsert_receipt(job_id, dossier={"outcome": "completed"})
    snapshot = ledger.get_snapshot(job_id)
    agent = summarize_receipt(snapshot, base_url="https://example.test")
    checks = list_job_summaries()[0]["active_checks"]
    assert checks == agent["active_checks"]
    assert checks["finding_count"] == 1 and checks["install_trace"] == "none"
    assert agent["findings"][0]["id"] == checks["leading_finding"]["id"]
    assert "Clean bill" not in agent["vuln_review"]
    assert ledger.get_vuln_report(job_id)["findings"] == []
    assert "active_checks" not in ledger.get_receipt(job_id)["dossier"]
    assert not ledger.import_active_findings(job_id)
    ledger.update_job_fields(job_id, status="completed")
    assert ledger.import_active_findings(job_id)
    assert ledger.get_vuln_report(job_id) == snapshot["vuln_report"]
    assert ledger.get_receipt(job_id) == snapshot["receipt"]
    assert not ledger.import_active_findings(job_id)
