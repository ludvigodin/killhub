"""Exercise Plane 1's trusted containment and cleanup ledger across restart and replay pruning."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from config import Settings
from finalize import evaluate_gates, finalize_job
from jobs import get_ledger, reset_ledger_for_tests
from ledger.store import Ledger, utc_now


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
    observation = ledger.append_event(
        job_id, typ="containment", message="observed boundary", payload=containment
    )

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
    assert dossier["containment_observation"] == {
        "event_id": observation.event_id,
        "generation": None,
    }
    assert dossier["gates"] == {
        "terminal": "failed",
        "reasons": ["containment_policy_bypass"],
        "hard_fail": True,
        "readiness_passed": True,
    }
    assert dossier["detonation_verdict"]["verdict"]["status"] == "SUSPICIOUS"
    assert dossier["detonation_verdict"]["findings"][0]["evidence"] == {
        "event_id": observation.event_id,
        "generation": None,
    }
    assert finalize_job(job_id, settings=settings, skip_scan=True).receipt == result.receipt


def test_install_bypass_survives_later_clean_observation(settings: Settings) -> None:
    ledger = get_ledger(settings)
    job_id = _ready_job(settings)
    observation = ledger.append_event(
        job_id,
        typ="log",
        message="observed boundary",
        payload={"classification": "policy_bypass", "probe_session": "install_cp_deny"},
    )
    # Install can stop before the offline matrix. Even a later clean matrix
    # cannot reverse a classification already recorded by the control plane.
    ledger.append_event(job_id, typ="containment", message="clean", payload={"claim": "proven"})
    ledger.append_event(job_id, typ="log", message="x" * 2048)
    assert not ledger.has_event(job_id, observation.event_id)

    result = finalize_job(job_id, settings=settings, skip_scan=True)

    assert result.terminal_status == "failed"
    assert result.receipt is not None
    assert result.receipt["dossier"]["gates"]["reasons"] == ["policy_bypass"]
    assert result.receipt["dossier"]["detonation_verdict"]["verdict"]["status"] == "SUSPICIOUS"
    assert result.receipt["dossier"]["policy_bypass"]["event_id"] == observation.event_id


@pytest.mark.parametrize("claim", ["proven", "incomplete"])
def test_without_bypass_readiness_remains_eligible(settings: Settings, claim: str) -> None:
    job_id = _ready_job(settings)
    get_ledger(settings).append_event(
        job_id,
        typ="containment",
        message="matrix recorded",
        payload={"claim": claim, "dimensions": {"host_liveness": {"ok": claim == "proven"}}},
    )
    result = finalize_job(job_id, settings=settings, skip_scan=True)
    assert result.terminal_status == "completed"
    assert result.receipt is not None
    proof = result.receipt["dossier"]["detonation_verdict"]["containment_proof"]
    assert proof["claim"] == "incomplete"
    assert proof["host_liveness"]["status"] == ("passed" if claim == "proven" else "inconclusive")


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
    result = finalize_job(job_id, settings=settings, skip_scan=True)
    assert result.terminal_status == "cancelled"
    assert (
        result.receipt is not None
        and result.receipt["containment"]["classification"] == "policy_bypass"
    )


def test_stale_containment_and_finalization_cannot_replace_newer_receipt(
    settings: Settings,
) -> None:
    ledger = get_ledger(settings)
    job_id = _ready_job(settings)
    observed = ledger.get_job(job_id)
    assert observed is not None
    generation = ledger.append_sandbox_generation(
        job_id, environment_id="current", image="ubuntu", expires_at=observed.expires_at
    )
    current = ledger.append_event(
        job_id,
        typ="containment",
        message="current matrix",
        payload={"claim": "incomplete"},
        expected_sandbox=(generation.generation, generation.environment_id),
    )
    with pytest.raises(Ledger.WriterFrozenError, match="sandbox changed"):
        ledger.append_event(
            job_id,
            typ="containment",
            message="stale matrix",
            payload={"claim": "incomplete", "classification": "policy_bypass"},
            expected_sandbox=(None, None),
        )
    ledger.finalize_job(
        job_id, status="failed", receipt={"lifecycle": {"confirmed": False}}, include_verdict=True
    )
    receipt = ledger.get_receipt(job_id)
    assert receipt is not None
    assert receipt["dossier"]["containment_observation"]["event_id"] == current.event_id
    with pytest.raises(Ledger.WriterFrozenError, match="job changed"):
        ledger.finalize_job(
            job_id,
            status="completed",
            receipt={"lifecycle": {"confirmed": True}, "containment": {}},
            expected_job=observed,
        )
    assert ledger.get_receipt(job_id) == receipt
