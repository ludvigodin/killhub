"""Queue position + soft ETA for pending/queued jobs (D40 UX)."""

from __future__ import annotations

from pathlib import Path

import pytest

from config import get_settings
from jobs import get_ledger, reset_ledger_for_tests
from service import (
    QUEUED_STATUSES,
    claim_pending_job,
    create_job,
    get_public_snapshot,
    list_job_summaries,
    queue_info_for_job,
)


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("MAX_QUEUED_JOBS", "8")
    monkeypatch.setenv("ESTIMATED_JOB_SECONDS", "600")
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def test_create_queued_when_slots_busy() -> None:
    cfg = get_settings()
    ledger = get_ledger(cfg)
    first = create_job("https://github.com/heroku/node-js-getting-started")
    # Occupy the sole concurrency slot.
    ledger.update_job_fields(first.job_id, status="analyzing", current_step="busy")

    second = create_job("https://github.com/modelcontextprotocol/servers")
    assert second.status == "queued"
    assert second.current_step == "in queue"

    info = queue_info_for_job(second, ledger=ledger, settings=cfg)
    assert info is not None
    assert info["queue_position"] == 1
    assert info["expected_wait_seconds"] == 600

    snap = get_public_snapshot(second.job_id)
    assert snap is not None
    assert snap["queue_position"] == 1
    assert snap["expected_wait_seconds"] == 600


def test_fifo_positions_and_claim_drains_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_settings()
    ledger = get_ledger(cfg)
    runner = create_job("https://github.com/heroku/node-js-getting-started")
    ledger.update_job_fields(runner.job_id, status="analyzing", current_step="busy")

    a = create_job("https://github.com/modelcontextprotocol/servers")
    b = create_job("https://github.com/heroku/python-getting-started")
    assert a.status == "queued"
    assert b.status == "queued"

    info_a = queue_info_for_job(a, ledger=ledger, settings=cfg)
    info_b = queue_info_for_job(b, ledger=ledger, settings=cfg)
    assert info_a is not None and info_b is not None
    # Same-second creates tie-break by job_id (matches list_jobs ORDER BY).
    assert {info_a["queue_position"], info_b["queue_position"]} == {1, 2}
    first_id = a.job_id if info_a["queue_position"] == 1 else b.job_id
    second_id = b.job_id if first_id == a.job_id else a.job_id

    summaries = {row["job_id"]: row for row in list_job_summaries(limit=10)}
    assert summaries[first_id]["queue_position"] == 1
    assert summaries[second_id]["queue_position"] == 2

    monkeypatch.setenv("DISCOVER_ON_CLAIM", "true")
    get_settings.cache_clear()

    claimed = claim_pending_job()
    assert claimed is not None
    assert claimed.job_id == first_id
    assert claimed.status == "analyzing"

    remaining = ledger.get_job(second_id)
    assert remaining is not None
    info_remaining = queue_info_for_job(remaining, ledger=ledger, settings=get_settings())
    assert info_remaining is not None
    assert info_remaining["queue_position"] == 1

    snap_claimed = get_public_snapshot(first_id)
    assert snap_claimed is not None
    assert snap_claimed["queue_position"] is None
    assert snap_claimed["expected_wait_seconds"] is None
    assert claimed.status not in QUEUED_STATUSES


def test_pending_also_exposes_queue_fields() -> None:
    cfg = get_settings()
    job = create_job("https://github.com/heroku/node-js-getting-started")
    assert job.status == "pending"
    info = queue_info_for_job(job, ledger=get_ledger(cfg), settings=cfg)
    assert info is not None
    assert info["queue_position"] == 1
    snap = get_public_snapshot(job.job_id)
    assert snap is not None
    assert snap["queue_position"] == 1
