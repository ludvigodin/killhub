"""Worker: failed readiness routes through finalize (PRODUCT_FIXES §1)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import worker
from config import get_settings
from harness import DestroyResult
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job
from verify import VerifyResult
from vulnscan import VulnScanResult


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("FINALIZE_ON_CLAIM", "true")
    monkeypatch.setenv("VERIFY_ON_CLAIM", "true")
    monkeypatch.setenv("INSTALL_ON_CLAIM", "false")
    monkeypatch.setenv("SCREENSHOTS_ON_CLAIM", "false")
    monkeypatch.setenv("CONTAINMENT_ON_CLAIM", "false")
    monkeypatch.setenv("ARTIFACT_STORAGE", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _seed_verifying_with_sandbox() -> str:
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-worker-fail",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.update_job_fields(
        job.job_id,
        status="installing",
        progress=80,
        resolved_commit="abc123",
    )
    return job.job_id


def test_verify_fail_skips_to_finalize_scan_and_destroy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_verifying_with_sandbox()
    cfg = get_settings()
    scan_calls: list[str] = []
    destroy_calls: list[str] = []
    containment_calls: list[str] = []
    screenshot_calls: list[str] = []

    def fake_discover(jid: str, **kwargs: Any) -> None:
        return None

    def fake_provision(jid: str, **kwargs: Any) -> None:
        return None

    def fake_verify(jid: str, **kwargs: Any) -> VerifyResult:
        ledger = get_ledger()
        readiness = {
            "passed": False,
            "probe": "http-root",
            "detail": {"ok": False},
            "at": "t",
        }
        verification = {
            "kind": "setup_failed",
            "original_failure": {"step": "verify", "summary": "probe failed"},
        }
        ledger.update_job_fields(
            jid,
            status="verifying",
            current_step="readiness failed — awaiting finalize",
            progress=90,
            readiness=readiness,
            verification=verification,
        )
        return VerifyResult(
            job_id=jid,
            environment_id="env-worker-fail",
            passed=False,
            verification_kind="setup_failed",
            readiness=readiness,
            verification=verification,
        )

    def fake_scan(jid: str, **kwargs: Any) -> VulnScanResult:
        scan_calls.append(jid)
        get_ledger().upsert_vuln_report(
            jid, summary="scanned", findings=[], status="ok", finalizer=True
        )
        return VulnScanResult(job_id=jid, status="ok", findings=[])

    def fake_destroy(jid: str, **kwargs: Any) -> DestroyResult:
        destroy_calls.append(jid)
        return DestroyResult(confirmed=True, error=None)

    monkeypatch.setattr("discover.discover_runtime_profile", fake_discover)
    monkeypatch.setattr("install.provision_and_go_offline", fake_provision)
    monkeypatch.setattr("verify.verify_readiness", fake_verify)
    monkeypatch.setattr("finalize.run_vuln_scan", fake_scan)
    monkeypatch.setattr("finalize.destroy_job_environment", fake_destroy)
    monkeypatch.setattr(
        "containment.run_containment_probes",
        lambda jid, **k: containment_calls.append(jid),
    )
    monkeypatch.setattr(
        "screenshots.maybe_capture_after_verify",
        lambda jid, **k: screenshot_calls.append(jid),
    )

    worker._run_pipeline_once(job_id, cfg, pipeline=True)

    assert scan_calls == [job_id]
    assert destroy_calls == [job_id]
    assert containment_calls == []
    assert screenshot_calls == []

    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status == "failed"
    assert job.destroyed_at is not None
    assert job.readiness and job.readiness.get("passed") is False
    assert get_ledger().get_receipt(job_id) is not None


def test_fail_claimed_job_reclaims_terminal_live_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = _seed_verifying_with_sandbox()
    ledger = get_ledger()
    ledger.finalize_job(
        job_id,
        status="failed",
        receipt={"verification": {"kind": "setup_failed"}, "dossier": {"outcome": "setup_failed"}},
        progress=100,
        current_step="premature terminal",
        error="premature",
    )
    reclaim = MagicMock(
        return_value=MagicMock(
            job_id=job_id,
            terminal_status="failed",
            destroyed=True,
            destroy_failed=False,
            receipt={},
            vuln_status="ok",
        )
    )
    monkeypatch.setattr("finalize.finalize_job", reclaim)

    class Boom(Exception):
        message = "pipeline boom"
        code = "boom"

    worker._fail_claimed_job(job_id, Boom(), ledger=ledger, settings=get_settings())
    reclaim.assert_called_once()
