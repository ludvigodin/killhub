"""Postgres LEDGER_URL parsing, engine selection, and optional live integration (D73)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ledger import Ledger, parse_ledger_url, parse_sqlite_path
from ledger.db import qmark_to_percent

URL = "https://github.com/heroku/node-js-getting-started"
POSTGRES_URL = os.environ.get("KILLHUB_TEST_POSTGRES_URL", "").strip()


def test_parse_sqlite_still_works(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    target = parse_ledger_url("sqlite:///./storage/ledger/killhub.db")
    assert target.engine == "sqlite"
    assert target.path == (tmp_path / "storage/ledger/killhub.db").resolve()
    assert parse_sqlite_path("sqlite:///./storage/ledger/killhub.db") == target.path


def test_parse_postgresql_and_postgres_schemes() -> None:
    pg = parse_ledger_url(
        "postgresql://vultradmin:s3cret@db.example:16751/defaultdb?sslmode=require"
    )
    assert pg.engine == "postgres"
    assert pg.dsn is not None
    assert pg.dsn.startswith("postgresql://")
    assert "sslmode=require" in pg.dsn
    assert pg.path is None

    alias = parse_ledger_url("postgres://u:p@host:5432/db")
    assert alias.engine == "postgres"
    assert alias.dsn == "postgresql://u:p@host:5432/db"


def test_parse_rejects_unknown_and_empty() -> None:
    with pytest.raises(ValueError, match="Unsupported LEDGER_URL scheme"):
        parse_ledger_url("mysql://localhost/db")
    with pytest.raises(ValueError, match="empty"):
        parse_ledger_url("   ")
    with pytest.raises(ValueError, match="missing host"):
        parse_ledger_url("postgresql:///onlydb")


def test_qmark_to_percent_placeholder_translation() -> None:
    assert qmark_to_percent("SELECT * FROM jobs WHERE job_id = ?") == (
        "SELECT * FROM jobs WHERE job_id = %s"
    )
    assert qmark_to_percent("UPDATE jobs SET a = ?, b = ? WHERE job_id = ?") == (
        "UPDATE jobs SET a = %s, b = %s WHERE job_id = %s"
    )


def test_from_url_selects_sqlite(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}"
    with Ledger.from_url(url) as ledger:
        assert ledger.engine == "sqlite"
        job = ledger.create_job(URL, env_ttl_seconds=60)
        assert ledger.get_job(job.job_id) is not None


def test_postgres_url_without_driver_or_server_fails_closed() -> None:
    """Fail closed: bad DSN must not silently fall back to SQLite."""
    # Unreachable host — connection error (driver is installed via requirements).
    url = "postgresql://killhub:killhub@127.0.0.1:1/killhub?connect_timeout=1"
    with pytest.raises(RuntimeError, match="Failed to connect|psycopg"):
        Ledger.from_url(url)


@pytest.mark.skipif(not POSTGRES_URL, reason="set KILLHUB_TEST_POSTGRES_URL to run live PG tests")
def test_live_postgres_transactions_cancel_and_cursor() -> None:
    """Optional integration: transactions, finalize (D61), SSE cursor (D55/D67)."""
    with Ledger.from_url(POSTGRES_URL, max_job_log_bytes=400) as ledger:
        assert ledger.engine == "postgres"
        job = ledger.create_job(URL, env_ttl_seconds=120)
        assert job.event_cursor == "1"

        ledger.append_event(job.job_id, typ="log", message="hello", payload={"k": 1})
        assert ledger.cursor_is_valid(job.job_id, "1")
        assert ledger.cursor_is_valid(job.job_id, "2")
        assert not ledger.cursor_is_valid(job.job_id, "999")

        ledger.update_job_fields(job.job_id, cancel_requested_at="2026-01-01T00:00:00Z")
        with pytest.raises(Ledger.WriterFrozenError):
            ledger.append_event(job.job_id, typ="log", message="blocked")

        finalized = ledger.finalize_job(
            job.job_id,
            status="cancelled",
            receipt={"dossier": {"why": "test"}},
            event_message="cancelled",
        )
        assert finalized.status == "cancelled"
        assert ledger.get_receipt(job.job_id) is not None

        # Contiguous prune + gap on Postgres too.
        job2 = ledger.create_job(
            "https://github.com/modelcontextprotocol/servers",
            env_ttl_seconds=60,
        )
        for i in range(20):
            ledger.append_event(
                job2.job_id,
                typ="log",
                message=f"payload-{i}-" + ("x" * 40),
                payload={"i": i, "blob": "y" * 40},
            )
        events = ledger.list_events(job2.job_id)
        assert any(e.type == "gap" for e in events)
        ids = [int(e.event_id) for e in events]
        assert ids == sorted(ids)
        assert ids[-1] - ids[0] + 1 == len(ids)
