"""Verify Plane 1 queue estimates and atomic claims with a real SQLite ledger."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from config import Settings
from jobs import get_ledger, reset_ledger_for_tests
from service import (
    QUEUED_STATUSES,
    claim_pending_job,
    create_job,
    get_public_snapshot,
    list_job_summaries,
    queue_info_for_job,
)


@pytest.fixture
def cfg(tmp_path: Path) -> Iterator[Settings]:
    settings = Settings(
        _env_file=None,
        LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        ADMISSION_STORE="memory",
        REAPER_ENABLED=False,
        PREFLIGHT_ENABLED=False,
        MSB_AUTO_CREATE=False,
        DISCOVER_ON_CLAIM=True,
        PUBLIC_DEMO_FIXTURES_ONLY=False,
        MAX_CONCURRENT_JOBS=1,
        MAX_QUEUED_JOBS=8,
        ESTIMATED_JOB_SECONDS=600,
    )
    try:
        yield settings
    finally:
        reset_ledger_for_tests()


def test_create_queued_when_slots_busy(cfg: Settings) -> None:
    ledger = get_ledger(cfg)
    first = create_job("https://github.com/heroku/node-js-getting-started", settings=cfg)
    # Occupy the sole concurrency slot.
    ledger.update_job_fields(first.job_id, status="analyzing", current_step="busy")

    second = create_job("https://github.com/modelcontextprotocol/servers", settings=cfg)
    assert second.status == "queued"
    assert second.current_step == "in queue"

    info = queue_info_for_job(second, ledger=ledger, settings=cfg)
    assert info is not None
    assert info["queue_position"] == 1
    assert info["expected_wait_seconds"] == 600

    snap = get_public_snapshot(second.job_id, settings=cfg)
    assert snap is not None
    assert snap["queue_position"] == 1
    assert snap["expected_wait_seconds"] == 600


def test_fifo_positions_and_claim_drains_queued(cfg: Settings) -> None:
    ledger = get_ledger(cfg)
    runner = create_job("https://github.com/heroku/node-js-getting-started", settings=cfg)
    ledger.update_job_fields(runner.job_id, status="analyzing", current_step="busy")

    a = create_job("https://github.com/modelcontextprotocol/servers", settings=cfg)
    b = create_job("https://github.com/heroku/python-getting-started", settings=cfg)
    assert a.status == "queued"
    assert b.status == "queued"

    info_a = queue_info_for_job(a, ledger=ledger, settings=cfg)
    info_b = queue_info_for_job(b, ledger=ledger, settings=cfg)
    assert info_a is not None and info_b is not None
    # Same-second creates tie-break by job_id (matches list_jobs ORDER BY).
    assert {info_a["queue_position"], info_b["queue_position"]} == {1, 2}
    first_id = a.job_id if info_a["queue_position"] == 1 else b.job_id
    second_id = b.job_id if first_id == a.job_id else a.job_id

    summaries = {row["job_id"]: row for row in list_job_summaries(limit=10, settings=cfg)}
    assert summaries[first_id]["queue_position"] == 1
    assert summaries[second_id]["queue_position"] == 2

    # Free the runner slot before simulating the periodic worker claim.
    ledger.finalize_job(runner.job_id, status="completed", receipt={}, current_step="completed")

    claimed = claim_pending_job(settings=cfg)
    assert claimed is not None
    assert claimed.job_id == first_id
    assert claimed.status == "analyzing"

    remaining = ledger.get_job(second_id)
    assert remaining is not None
    info_remaining = queue_info_for_job(remaining, ledger=ledger, settings=cfg)
    assert info_remaining is not None
    assert info_remaining["queue_position"] == 1

    snap_claimed = get_public_snapshot(first_id, settings=cfg)
    assert snap_claimed is not None
    assert snap_claimed["queue_position"] is None
    assert snap_claimed["expected_wait_seconds"] is None
    assert claimed.status not in QUEUED_STATUSES


def test_pending_also_exposes_queue_fields(cfg: Settings) -> None:
    job = create_job("https://github.com/heroku/node-js-getting-started", settings=cfg)
    assert job.status == "pending"
    info = queue_info_for_job(job, ledger=get_ledger(cfg), settings=cfg)
    assert info is not None
    assert info["queue_position"] == 1
    snap = get_public_snapshot(job.job_id, settings=cfg)
    assert snap is not None
    assert snap["queue_position"] == 1


def test_an_available_slot_has_no_wait(cfg: Settings) -> None:
    cfg = cfg.model_copy(update={"max_concurrent_jobs": 2})
    ledger = get_ledger(cfg)
    runner = create_job("https://github.com/heroku/node-js-getting-started", settings=cfg)
    ledger.update_job_fields(runner.job_id, status="analyzing", current_step="busy")

    waiting = create_job("https://github.com/modelcontextprotocol/servers", settings=cfg)
    assert waiting.status == "pending"
    snapshot = get_public_snapshot(waiting.job_id, settings=cfg)
    assert snapshot is not None
    assert snapshot["queue_position"] == 1
    assert snapshot["expected_wait_seconds"] == 0
