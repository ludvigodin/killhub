"""Verify Plane 1 finalization reads durable containment evidence after replay pruning."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from config import Settings
from finalize import evaluate_gates, finalize_job
from jobs import get_ledger, reset_ledger_for_tests
from ledger.store import utc_now


@pytest.fixture
def settings(tmp_path: Path) -> Iterator[Settings]:
    cfg = Settings(
        _env_file=None,
        LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        ADMISSION_STORE="memory",
        MAX_JOB_LOG_BYTES=1024,
    )
    try:
        yield cfg
    finally:
        reset_ledger_for_tests()


def _ready_job(settings: Settings) -> str:
    ledger = get_ledger(settings)
    job = ledger.create_job(
        "https://github.com/example/fixture", env_ttl_seconds=300, status="verifying"
    )
    ledger.update_job_fields(
        job.job_id,
        readiness={"passed": True, "probe": "http-root"},
        verification={"kind": "original_application"},
    )
    return job.job_id


@pytest.mark.parametrize(
    "containment",
    [
        {"dimensions": {"host_access_denied": {"classification": "policy_bypass"}}},
        {"install_cp_probe": {"classification": "policy_bypass"}},
        {"network_probes": [{"classification": "policy_bypass"}]},
    ],
)
def test_finalize_retains_bypass_after_pruning_and_restart(
    settings: Settings, containment: dict[str, Any]
) -> None:
    ledger = get_ledger(settings)
    job_id = _ready_job(settings)
    containment = {"claim": "incomplete", **containment}
    ledger.append_event(job_id, typ="containment", message="observed boundary", payload=containment)
    ledger.upsert_receipt(job_id, containment=containment, dossier={"containment_at": utc_now()})

    # Drive normal retention, then reopen the same database as a restarted worker.
    ledger.append_event(job_id, typ="log", message="x" * 2048)
    assert not any(event.type == "containment" for event in ledger.list_events(job_id))
    reset_ledger_for_tests()

    result = finalize_job(job_id, settings=settings, skip_scan=True)
    assert result.terminal_status == "failed"
    assert result.receipt is not None
    assert result.receipt["containment"] == containment
    dossier = result.receipt["dossier"]
    assert dossier["containment_at"]
    assert dossier["gates"] == {
        "terminal": "failed",
        "reasons": ["containment_policy_bypass"],
        "hard_fail": True,
        "readiness_passed": True,
    }
    assert dossier["detonation_verdict"]["verdict"]["status"] == "SUSPICIOUS"
    assert finalize_job(job_id, settings=settings, skip_scan=True).receipt == result.receipt


def test_legacy_finding_is_persisted_in_the_gate(settings: Settings) -> None:
    ledger = get_ledger(settings)
    job_id = _ready_job(settings)
    ledger.append_event(
        job_id,
        typ="finding",
        message="observed boundary",
        payload={"classification": "policy_bypass"},
    )

    result = finalize_job(job_id, settings=settings, skip_scan=True)

    assert result.terminal_status == "failed"
    assert result.receipt is not None
    assert result.receipt["dossier"]["gates"]["reasons"] == ["policy_bypass"]
    assert result.receipt["dossier"]["detonation_verdict"]["verdict"]["status"] == "SUSPICIOUS"


def test_incomplete_containment_keeps_readiness_eligible(settings: Settings) -> None:
    job_id = _ready_job(settings)
    get_ledger(settings).upsert_receipt(
        job_id, containment={"claim": "incomplete", "dimensions": {"host_liveness": {"ok": False}}}
    )
    assert evaluate_gates(job_id, settings=settings)["terminal"] == "completed"


@pytest.mark.parametrize(("source", "terminal"), [("network", "failed"), ("sca", "completed")])
def test_only_host_policy_findings_in_the_dossier_can_hard_fail(
    settings: Settings, source: str, terminal: str
) -> None:
    job_id = _ready_job(settings)
    get_ledger(settings).upsert_receipt(
        job_id,
        dossier={"findings": [{"source": source, "classification": "policy_bypass"}]},
    )
    assert evaluate_gates(job_id, settings=settings)["terminal"] == terminal


def test_cancellation_keeps_precedence_over_a_bypass(settings: Settings) -> None:
    ledger = get_ledger(settings)
    job_id = _ready_job(settings)
    ledger.upsert_receipt(job_id, containment={"classification": "policy_bypass"})
    ledger.update_job_fields(job_id, cancel_requested_at=utc_now())
    assert evaluate_gates(job_id, settings=settings)["terminal"] == "cancelled"
