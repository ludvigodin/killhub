"""Heartbeats for long-running sandbox waits (Activity log density)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from config import get_settings
from job_pulse import with_heartbeat
from jobs import get_ledger, reset_ledger_for_tests


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def test_with_heartbeat_emits_start_and_elapsed_logs() -> None:
    cfg = get_settings()
    ledger = get_ledger(cfg)
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=600,
    )

    def slow() -> str:
        time.sleep(0.35)
        return "done"

    result = with_heartbeat(
        job.job_id,
        settings=cfg,
        label="testing pulse",
        fn=slow,
        interval_seconds=0.1,
    )
    assert result == "done"

    events = ledger.list_events(job.job_id)
    messages = [e.message for e in events if e.type == "log"]
    assert any(m == "testing pulse…" for m in messages)
    assert any(m.startswith("still testing pulse (") for m in messages)


def test_with_heartbeat_announce_false_skips_start_log() -> None:
    cfg = get_settings()
    ledger = get_ledger(cfg)
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=600,
    )

    with_heartbeat(
        job.job_id,
        settings=cfg,
        label="quiet create",
        fn=lambda: None,
        announce=False,
        interval_seconds=60,
    )
    events = ledger.list_events(job.job_id)
    messages = [e.message for e in events if e.type == "log"]
    assert "quiet create…" not in messages
