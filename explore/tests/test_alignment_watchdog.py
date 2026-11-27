"""Exercise Plane 1 watchdog decisions and public evidence with a real SQLite ledger."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from config import Settings
from harness import CliResult, MsbCli
from jobs import get_ledger, reset_ledger_for_tests
from safety import summary_safety
from stall import fail_job


def _unexpected_cli(args: Sequence[str], timeout: float | None) -> CliResult:
    pytest.fail("No host CLI call should be needed for this watchdog decision.")


def test_expiry_keeps_confirmed_cleanup_and_receipt_evidence(tmp_path: Path) -> None:
    cfg = Settings(
        _env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}", ADMISSION_STORE="memory"
    )
    ledger = get_ledger(cfg)
    try:
        job = ledger.create_job(
            "https://github.com/example/fixture", env_ttl_seconds=60, status="verifying"
        )
        gen = ledger.append_sandbox_generation(
            job.job_id, environment_id="kh-expired", image="debian", expires_at=job.expires_at
        )
        ledger.upsert_receipt(job.job_id, dossier={"prior_evidence": "preserved"})
        ledger.record_reaped_cleanup(
            job.job_id, gen.generation, gen.environment_id, confirmed=True, error=None
        )
        observed = ledger.get_job(job.job_id)

        action = fail_job(
            job.job_id,
            code="expires_at",
            reason="Deadline elapsed.",
            settings=cfg,
            cli=MsbCli(cfg, runner=_unexpected_cli),
            observed=observed,
        )

        assert action["finalized"] and action["confirmed_destroy"]
        receipt = ledger.get_receipt(job.job_id)
        assert receipt["lifecycle"]["destroyed_at"] == observed.destroyed_at
        assert receipt["dossier"]["prior_evidence"] == "preserved"
        assert receipt["dossier"]["detonation_verdict"]["verdict"]["status"] == "ABORTED"
    finally:
        reset_ledger_for_tests()


def test_fresh_heartbeat_invalidates_a_stalled_observation(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)
    try:
        job = ledger.create_job(
            "https://github.com/example/fixture", env_ttl_seconds=60, status="installing"
        )
        ledger.append_event(job.job_id, typ="log", message="worker progress")
        action = fail_job(
            job.job_id,
            code="job_stalled",
            reason="Missing activity.",
            settings=cfg,
            cli=MsbCli(cfg, runner=_unexpected_cli),
            observed=job,
        )
        assert not action["finalized"]
        assert ledger.get_job(job.job_id).status == "installing"
        assert ledger.get_receipt(job.job_id) is None
    finally:
        reset_ledger_for_tests()


@pytest.mark.parametrize(
    ("verdict_status", "outcome"), [("INCONCLUSIVE", "unknown"), ("SUSPICIOUS", "high_risk")]
)
def test_feed_safety_uses_persisted_verdict(verdict_status: str, outcome: str) -> None:
    receipt = {
        "containment": {"claim": "proven"},
        "dossier": {"detonation_verdict": {"verdict": {"status": verdict_status}}},
    }
    assert (
        summary_safety(
            status="completed",
            verification={"kind": "original_application"},
            vuln_report={"status": "ok", "findings": []},
            receipt=receipt,
        )
        == outcome
    )
