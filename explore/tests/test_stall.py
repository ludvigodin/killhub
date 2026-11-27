"""Job timeout / stall / expires_at terminalization (D83)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from config import Settings
from ledger import Ledger
from stall import classify_stale_job, fail_job, reap_stale_jobs


def _cfg(tmp_path, **kwargs: object) -> Settings:
    opts: dict[str, object] = {
        "LEDGER_URL": f"sqlite:///{tmp_path}/ledger.db",
        "JOB_TIMEOUT_SECONDS": 3600,
        "JOB_STALL_SECONDS": 600,
        "ENV_TTL_SECONDS": 7200,
    }
    opts.update(kwargs)
    return Settings(**opts)  # type: ignore[arg-type]


def test_classify_job_timeout(tmp_path):
    cfg = _cfg(tmp_path, JOB_TIMEOUT_SECONDS=60)
    with Ledger.from_url(cfg.ledger_url) as ledger:
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=7200)
        ledger.update_job_fields(job.job_id, status="analyzing", current_step="stuck")
        job = ledger.get_job(job.job_id)
        assert job is not None
        now = datetime.now(timezone.utc) + timedelta(seconds=90)
        assert classify_stale_job(job, now=now, settings=cfg) == "job_timeout"


def test_classify_job_stalled(tmp_path):
    cfg = _cfg(tmp_path, JOB_STALL_SECONDS=30, JOB_TIMEOUT_SECONDS=86_400)
    with Ledger.from_url(cfg.ledger_url) as ledger:
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=7200)
        ledger.update_job_fields(
            job.job_id,
            status="analyzing",
            current_step="worker stub: analyzing",
            progress=5,
        )
        past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        ledger._conn.execute(  # noqa: SLF001 — test fixture
            "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
            (past, job.job_id),
        )
        job = ledger.get_job(job.job_id)
        assert job is not None
        assert (
            classify_stale_job(job, now=datetime.now(timezone.utc), settings=cfg) == "job_stalled"
        )


def test_classify_expires_at_without_sandbox(tmp_path):
    cfg = _cfg(tmp_path, JOB_TIMEOUT_SECONDS=86_400, JOB_STALL_SECONDS=86_400)
    with Ledger.from_url(cfg.ledger_url) as ledger:
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=1)
        ledger.update_job_fields(job.job_id, status="analyzing", current_step="analyzing")
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        ledger._conn.execute(  # noqa: SLF001
            "UPDATE jobs SET expires_at = ?, updated_at = ? WHERE job_id = ?",
            (past, datetime.now(timezone.utc).isoformat(), job.job_id),
        )
        job = ledger.get_job(job.job_id)
        assert job is not None
        assert classify_stale_job(job, now=datetime.now(timezone.utc), settings=cfg) == "expires_at"


def test_reap_stale_jobs_finalizes_without_sandbox(tmp_path, monkeypatch):
    import jobs

    cfg = _cfg(tmp_path, JOB_TIMEOUT_SECONDS=1, JOB_STALL_SECONDS=86_400)
    jobs.reset_ledger_for_tests()
    monkeypatch.setenv("LEDGER_URL", cfg.ledger_url)
    from config import get_settings

    get_settings.cache_clear()
    ledger = jobs.init_ledger(cfg)
    try:
        monkeypatch.setattr("stall.get_ledger", lambda _settings=None: ledger)
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=7200)
        ledger.update_job_fields(
            job.job_id,
            status="analyzing",
            current_step="worker stub: analyzing",
            progress=5,
        )
        past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        ledger._conn.execute(  # noqa: SLF001
            "UPDATE jobs SET created_at = ?, updated_at = ? WHERE job_id = ?",
            (past, past, job.job_id),
        )

        cli = MagicMock()
        actions = reap_stale_jobs(
            settings=cfg,
            cli=cli,
            now=datetime.now(timezone.utc),
        )
        assert any(a.get("finalized") and a.get("reason") == "job_timeout" for a in actions)
        recovered = ledger.get_job(job.job_id)
        assert recovered is not None
        assert recovered.status == "failed"
        receipt = ledger.get_receipt(job.job_id)
        assert receipt is not None
        assert receipt["dossier"]["code"] == "job_timeout"
    finally:
        jobs.reset_ledger_for_tests()
        get_settings.cache_clear()


def test_fail_job_idempotent_when_terminal(tmp_path, monkeypatch):
    import jobs

    cfg = _cfg(tmp_path)
    jobs.reset_ledger_for_tests()
    monkeypatch.setenv("LEDGER_URL", cfg.ledger_url)
    from config import get_settings

    get_settings.cache_clear()
    ledger = jobs.init_ledger(cfg)
    try:
        monkeypatch.setattr("stall.get_ledger", lambda _settings=None: ledger)
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=120)
        ledger.finalize_job(
            job.job_id,
            status="failed",
            receipt={"dossier": {"outcome": "failed", "code": "already"}},
            current_step="failed",
            progress=100,
            error="done",
        )
        out = fail_job(
            job.job_id,
            code="job_stalled",
            reason="should no-op",
            settings=cfg,
            destroy=False,
        )
        assert out["finalized"] is False
        assert ledger.get_receipt(job.job_id)["dossier"]["code"] == "already"
    finally:
        jobs.reset_ledger_for_tests()
        get_settings.cache_clear()


def test_pending_not_stalled_by_silence(tmp_path):
    cfg = _cfg(tmp_path, JOB_STALL_SECONDS=1, JOB_TIMEOUT_SECONDS=86_400)
    with Ledger.from_url(cfg.ledger_url) as ledger:
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=7200)
        past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
        ledger._conn.execute(  # noqa: SLF001
            "UPDATE jobs SET updated_at = ? WHERE job_id = ?",
            (past, job.job_id),
        )
        job = ledger.get_job(job.job_id)
        assert job is not None
        assert job.status == "pending"
        assert classify_stale_job(job, now=datetime.now(timezone.utc), settings=cfg) is None
