"""Focused ledger transaction + restart + pruning tests (D41, D64, D67)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ledger import Ledger, parse_sqlite_path


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger" / "killhub.db"


def test_parse_sqlite_relative_and_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rel = parse_sqlite_path("sqlite:///./storage/ledger/killhub.db")
    assert rel == (tmp_path / "storage/ledger/killhub.db").resolve()
    absolute = (tmp_path / "abs.db").resolve()
    # Four slashes: sqlite:/// + /abs/path → sqlite:////abs/path
    abs_path = parse_sqlite_path("sqlite:///" + absolute.as_posix())
    assert abs_path == absolute


def test_create_job_append_event_and_snapshot_atomic(db_path: Path) -> None:
    with Ledger(db_path, max_job_log_bytes=1_000_000) as ledger:
        job = ledger.create_job(
            "https://github.com/heroku/node-js-getting-started",
            env_ttl_seconds=3600,
        )
        assert job.status == "pending"
        assert job.event_cursor == "1"
        assert job.cleanup.status == "pending"

        event = ledger.append_event(
            job.job_id,
            typ="log",
            message="hello",
            payload={"kind": "agent"},
        )
        assert event.event_id == "2"

        snap = ledger.get_snapshot(job.job_id)
        assert snap is not None
        assert snap["job_id"] == job.job_id
        assert snap["event_cursor"] == "2"
        assert snap["git_url"] == "https://github.com/heroku/node-js-getting-started"
        assert ledger.list_events(job.job_id)[0].type == "status"


def test_profile_revision_and_sandbox_generation_pointers(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(
            "https://github.com/modelcontextprotocol/servers",
            env_ttl_seconds=7200,
        )
        rev = ledger.append_profile_revision(
            job.job_id,
            phase="bootstrap",
            schema_version="1",
            profile={"schema_version": "1", "intent": "bootstrap"},
        )
        assert rev.revision == 1
        gen = ledger.append_sandbox_generation(
            job.job_id,
            environment_id="msb-demo-1",
            image="ghcr.io/example/bootstrap:latest",
            expires_at=job.expires_at,
            state="running",
            cpus=2,
            memory="4Gi",
        )
        assert gen.generation == 1

        refreshed = ledger.get_job(job.job_id)
        assert refreshed is not None
        assert refreshed.current_profile_revision == 1
        assert refreshed.current_sandbox_generation == 1
        assert refreshed.sandbox_id == "msb-demo-1"

        # Replace: mark prior generation replaced without job-level destroyed_at (D64).
        ledger.mark_generation_state(
            job.job_id,
            1,
            "replaced",
            destroyed_at="2026-01-01T00:00:00Z",
        )
        gen2 = ledger.append_sandbox_generation(
            job.job_id,
            environment_id="msb-demo-2",
            image="ghcr.io/example/runtime:latest",
            expires_at=job.expires_at,
            state="running",
        )
        refreshed = ledger.get_job(job.job_id)
        assert refreshed is not None
        assert refreshed.current_sandbox_generation == 2
        assert refreshed.sandbox_id == "msb-demo-2"
        assert refreshed.destroyed_at is None
        assert gen2.expires_at == job.expires_at


def test_event_prune_is_contiguous_with_gap_tombstone(db_path: Path) -> None:
    with Ledger(db_path, max_job_log_bytes=400) as ledger:
        job = ledger.create_job(
            "https://github.com/heroku/node-js-getting-started",
            env_ttl_seconds=60,
        )
        for i in range(20):
            ledger.append_event(
                job.job_id,
                typ="log",
                message=f"payload-{i}-" + ("x" * 40),
                payload={"i": i, "blob": "y" * 40},
            )

        events = ledger.list_events(job.job_id)
        assert events, "expected retained events"
        assert any(e.type == "gap" for e in events)
        gap = next(e for e in events if e.type == "gap")
        assert "pruned_before_event_id" in gap.payload
        assert "bytes_freed" in gap.payload

        # Contiguous numeric ids among retained events (gap reuses pruned id).
        ids = [int(e.event_id) for e in events]
        assert ids == sorted(ids)
        assert ids[-1] - ids[0] + 1 == len(ids)

        assert ledger.retained_event_bytes(job.job_id) <= 400
        refreshed = ledger.get_job(job.job_id)
        assert refreshed is not None
        assert refreshed.event_cursor == events[-1].event_id


def test_restart_preserves_jobs_and_events(db_path: Path) -> None:
    job_id: str
    with Ledger(db_path) as ledger:
        job = ledger.create_job(
            "https://github.com/heroku/node-js-getting-started",
            env_ttl_seconds=120,
        )
        job_id = job.job_id
        ledger.append_event(job_id, typ="progress", message="10%", payload={"progress": 10})
        ledger.append_profile_revision(
            job_id,
            phase="runtime",
            schema_version="1",
            profile={"schema_version": "1", "intent": "webapp"},
        )

    # Process "restart": new connection to same file.
    with Ledger(db_path) as ledger:
        snap = ledger.get_snapshot(job_id)
        assert snap is not None
        assert snap["status"] == "pending"
        assert snap["event_cursor"] == "2"
        assert snap["current_profile_revision"] == 1
        events = ledger.list_events(job_id)
        assert len(events) == 2
        assert events[1].type == "progress"


def test_reconcile_startup_flags_expired_generations(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(
            "https://github.com/heroku/node-js-getting-started",
            env_ttl_seconds=1,
        )
        past = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        future = (
            (datetime.now(timezone.utc) + timedelta(hours=1))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        ledger.update_job_fields(job.job_id, expires_at=past)
        ledger.append_sandbox_generation(
            job.job_id,
            environment_id="old-vm",
            image="img:1",
            expires_at=past,
            state="running",
        )
        # Second job still live.
        job2 = ledger.create_job(
            "https://github.com/modelcontextprotocol/servers",
            env_ttl_seconds=3600,
        )
        ledger.append_sandbox_generation(
            job2.job_id,
            environment_id="live-vm",
            image="img:2",
            expires_at=future,
            state="running",
        )

        report = ledger.reconcile_startup(
            live_environment_ids={"live-vm", "ghost-vm"},
            now=datetime.now(timezone.utc),
        )
        assert report.job_count == 2
        assert any(g.environment_id == "old-vm" for g in report.expired_generations)
        assert any(g.environment_id == "live-vm" for g in report.live_generations)
        assert any("ghost-vm" in n for n in report.orphan_notes)


def test_reject_non_allowlisted_git_url(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        with pytest.raises(ValueError, match="github.com|gitlab.com|bitbucket.org|codeberg.org"):
            ledger.create_job("https://example.com/org/repo", env_ttl_seconds=60)


def test_accept_allowlisted_git_urls(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        gh = ledger.create_job(
            "https://github.com/org/repo.git",
            env_ttl_seconds=60,
        )
        assert gh.git_url == "https://github.com/org/repo"
        gl = ledger.create_job(
            "https://gitlab.com/group/sub/project",
            env_ttl_seconds=60,
        )
        assert gl.git_url == "https://gitlab.com/group/sub/project"
        bb = ledger.create_job(
            "https://bitbucket.org/team/repo/",
            env_ttl_seconds=60,
        )
        assert bb.git_url == "https://bitbucket.org/team/repo"
        cb = ledger.create_job(
            "https://codeberg.org/user/repo",
            env_ttl_seconds=60,
        )
        assert cb.git_url == "https://codeberg.org/user/repo"
