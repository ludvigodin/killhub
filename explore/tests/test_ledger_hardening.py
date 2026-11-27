"""Ledger migrations, receipt-before-terminal (D61), vuln reports and protected pruning (D67)."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from ledger import Ledger
from ledger.migrations import LedgerVersionError, Migration, latest_version, migrate
from ledger.schema import SCHEMA_SQL

URL = "https://github.com/heroku/node-js-getting-started"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger" / "killhub.db"


def _meta(db_path: Path, key: str) -> str | None:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM ledger_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


# --- migrations ----------------------------------------------------------------


def test_fresh_ledger_is_stamped_with_latest_version(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        assert ledger.schema_version == latest_version()
    assert _meta(db_path, "schema_version") == str(latest_version())
    assert _meta(db_path, "engine") == "sqlite"


def test_reopen_keeps_data_and_version(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
    with Ledger(db_path) as ledger:
        assert ledger.get_job(job.job_id) is not None
        assert ledger.schema_version == latest_version()


def test_shared_sqlite_ledger_serializes_concurrent_events(db_path: Path) -> None:
    """API and worker threads share a ledger, so their writes must commit independently."""
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        workers = 8
        barrier = Barrier(workers)

        def append(index: int) -> None:
            barrier.wait(timeout=5)
            ledger.append_event(job.job_id, typ="log", message=f"writer {index}")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(append, range(workers)))

        events = ledger.list_events(job.job_id, after_event_id=job.event_cursor)
        assert {event.message for event in events} == {f"writer {i}" for i in range(workers)}
        assert [event.event_id for event in events] == [str(i) for i in range(2, workers + 2)]


def test_pending_migrations_apply_in_order_with_backup(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)

    applied: list[int] = []

    def add_column(conn: sqlite3.Connection) -> None:
        applied.append(2)
        conn.execute("ALTER TABLE jobs ADD COLUMN target_type TEXT NOT NULL DEFAULT 'github_repo'")

    def add_index(conn: sqlite3.Connection) -> None:
        applied.append(3)
        conn.execute("CREATE INDEX idx_jobs_status ON jobs(status)")

    # Exercise custom migrations after the project's current schema.
    initial = latest_version()
    migrations = [
        Migration(initial + 2, "index", add_index),
        Migration(initial + 1, "column", add_column),
    ]
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        assert migrate(conn, db_path, migrations) == initial + 2
        row = conn.execute(
            "SELECT target_type FROM jobs WHERE job_id = ?", (job.job_id,)
        ).fetchone()
    finally:
        conn.close()

    assert applied == [2, 3]
    assert row is not None
    assert row[0] == "github_repo"
    assert _meta(db_path, "schema_version") == str(initial + 2)
    backup = db_path.with_name(f"{db_path.name}.pre-v{initial + 1}.bak")
    assert backup.exists()
    with sqlite3.connect(backup) as bconn:
        assert bconn.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()[
            0
        ] == str(initial)


def test_failed_migration_rolls_back_and_keeps_version(db_path: Path) -> None:
    Ledger(db_path).close()

    def boom(conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE jobs ADD COLUMN half_done TEXT")
        raise RuntimeError("migration failed")

    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        with pytest.raises(RuntimeError, match="migration failed"):
            migrate(conn, db_path, [Migration(latest_version() + 1, "boom", boom)])
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    finally:
        conn.close()
    assert "half_done" not in cols
    assert _meta(db_path, "schema_version") == str(latest_version())


def test_newer_ledger_is_refused(db_path: Path) -> None:
    Ledger(db_path).close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE ledger_meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(LedgerVersionError):
        Ledger(db_path)


def test_legacy_ledger_without_meta_is_treated_as_v1(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        # Recreate the v1 shape so opening the ledger exercises the real migration.
        conn.execute("DROP TABLE sandbox_checkout_integrity")
        conn.execute("DROP TABLE ledger_meta")
    with Ledger(db_path) as ledger:
        assert ledger.schema_version == latest_version()
    assert _meta(db_path, "schema_version") == str(latest_version())
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sandbox_checkout_integrity").fetchone() == (0,)


def test_migration_versions_must_be_unique(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None)
    noop = lambda _c: None  # noqa: E731
    try:
        with pytest.raises(ValueError):
            migrate(conn, db_path, [Migration(2, "a", noop), Migration(2, "b", noop)])
        with pytest.raises(ValueError):
            migrate(conn, db_path, [Migration(1, "baseline clash", noop)])
    finally:
        conn.close()


# --- receipt before terminal (D61) -----------------------------------------------


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_status_requires_receipt(db_path: Path, status: str) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        with pytest.raises(Ledger.ReceiptRequiredError):
            ledger.update_job_fields(job.job_id, status=status)
        with pytest.raises(Ledger.ReceiptRequiredError):
            ledger.update_job_fields(job.job_id, finalizer=True, status=status)
        assert ledger.get_job(job.job_id).status == "pending"  # type: ignore[union-attr]


def test_non_terminal_status_needs_no_receipt(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        assert ledger.update_job_fields(job.job_id, status="verifying").status == "verifying"


def test_finalize_job_writes_receipt_event_and_status_atomically(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        done = ledger.finalize_job(
            job.job_id,
            status="failed",
            receipt={"verification": {"kind": "setup_failed"}, "dossier": {"outcome": "failed"}},
            event_payload={"reason": "test"},
            error="boom",
            progress=100,
        )
        assert done.status == "failed" and done.error == "boom" and done.progress == 100
        receipt = ledger.get_receipt(job.job_id)
        assert receipt is not None
        assert receipt["verification"] == {"kind": "setup_failed"}
        last = ledger.list_events(job.job_id)[-1]
        assert last.type == "status"
        assert last.payload == {"status": "failed", "reason": "test"}
        assert done.event_cursor == last.event_id


def test_finalize_job_merges_existing_receipt(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        ledger.upsert_receipt(job.job_id, containment={"claim": "complete"}, dossier={"a": 1})
        ledger.finalize_job(job.job_id, status="completed", receipt={"dossier": {"b": 2}})
        receipt = ledger.get_receipt(job.job_id)
        assert receipt is not None
        assert receipt["containment"] == {"claim": "complete"}
        assert receipt["dossier"] == {"b": 2}


def test_invalid_verdict_keeps_terminal_write_atomic(db_path: Path) -> None:
    """A verdict validation failure must leave the last durable state intact."""
    from jsonschema import ValidationError

    from verdict import verdict_validator

    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        prior = ledger.upsert_receipt(job.job_id, dossier={"evidence": "prior"})
        invalid_job = ledger.update_job_fields(job.job_id, resolved_commit="")
        with pytest.raises(ValidationError):
            ledger.finalize_job(job.job_id, status="failed", receipt={}, include_verdict=True)
        assert ledger.get_receipt(job.job_id) == prior
        assert ledger.get_job(job.job_id) == invalid_job
        assert [event.payload["status"] for event in ledger.list_events(job.job_id)] == ["pending"]
        # A rollback also releases the writer lock for a subsequent valid finalize.
        ledger.update_job_fields(job.job_id, resolved_commit="a" * 40)
        final = ledger.finalize_job(job.job_id, status="failed", receipt={}, include_verdict=True)
        assert final.status == "failed"
        verdict = ledger.get_receipt(job.job_id)["dossier"]["detonation_verdict"]
        assert verdict_validator().is_valid(verdict)


def test_finalize_job_rolls_back_on_bad_field(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        with pytest.raises(ValueError):
            ledger.finalize_job(job.job_id, status="failed", receipt={}, not_a_field=1)
        with pytest.raises(ValueError):
            ledger.finalize_job(job.job_id, status="verifying", receipt={})  # type: ignore[arg-type]
        assert ledger.get_receipt(job.job_id) is None
        assert ledger.get_job(job.job_id).status == "pending"  # type: ignore[union-attr]


def test_finalize_job_works_on_cancel_frozen_job(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        ledger.update_job_fields(job.job_id, cancel_requested_at="2026-01-01T00:00:00Z")
        with pytest.raises(Ledger.WriterFrozenError):
            ledger.update_job_fields(job.job_id, progress=50)
        done = ledger.finalize_job(job.job_id, status="cancelled", receipt={"dossier": {}})
        assert done.status == "cancelled"


# --- vuln reports ----------------------------------------------------------------


def _finding(**over: object) -> dict[str, object]:
    base = {"id": "GHSA-1", "severity": "high", "title": "proto pollution", "source": "sca"}
    return {**base, **over}


def test_upsert_vuln_report_roundtrip_and_overwrite(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        ledger.upsert_vuln_report(
            job.job_id, summary="first", findings=[_finding()], status="partial"
        )
        report = ledger.upsert_vuln_report(
            job.job_id,
            summary="cite-checked",
            findings=[_finding(), _finding(id="app-1", source="intentional_app")],
            status="ok",
            mcp_assessment={"tools": 3},
        )
        assert report["summary"] == "cite-checked"
        assert report["status"] == "ok"
        assert [f["source"] for f in report["findings"]] == ["sca", "intentional_app"]
        assert report["mcp_assessment"] == {"tools": 3}


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"status": "great"}, "status"),
        ({"findings": [{"severity": "low", "title": "t", "source": "sca"}]}, "missing id"),
        ({"findings": [{"id": "x", "severity": "low", "title": "t"}]}, "unknown source"),
        ({"findings": [_finding(source="vibes")]}, "unknown source"),
    ],
)
def test_upsert_vuln_report_validates(db_path: Path, kwargs: dict, match: str) -> None:
    args = {"summary": "s", "findings": [_finding()], "status": "ok", **kwargs}
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        with pytest.raises(ValueError, match=match):
            ledger.upsert_vuln_report(job.job_id, **args)
        assert ledger.get_vuln_report(job.job_id) is None


def test_upsert_vuln_report_respects_cancel_freeze(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        ledger.update_job_fields(job.job_id, cancel_requested_at="2026-01-01T00:00:00Z")
        with pytest.raises(Ledger.WriterFrozenError):
            ledger.upsert_vuln_report(job.job_id, summary="s", findings=[], status="ok")
        ledger.upsert_vuln_report(
            job.job_id, summary="s", findings=[], status="partial", finalizer=True
        )
        assert ledger.get_vuln_report(job.job_id)["status"] == "partial"  # type: ignore[index]


# --- protected pruning (D67 rule 3) -------------------------------------------------


def _fill(ledger: Ledger, job_id: str, n: int) -> None:
    for i in range(n):
        ledger.append_event(
            job_id, typ="log", message=f"log line {i:04d} " + "x" * 40, finalizer=True
        )


def test_prune_stops_at_destroy_evidence_without_receipt(db_path: Path) -> None:
    with Ledger(db_path, max_job_log_bytes=1500) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        ledger.append_event(
            job.job_id, typ="lifecycle", message="destroyed", payload={"phase": "destroyed"}
        )
        _fill(ledger, job.job_id, 60)
        types = [e.type for e in ledger.list_events(job.job_id)]
        assert "lifecycle" in types, "destroy evidence must survive until the receipt exists"
        # Retained window is still contiguous (only a prefix before the evidence may go).
        ids = [int(e.event_id) for e in ledger.list_events(job.job_id)]
        assert ids == sorted(ids)


def test_prune_may_drop_destroy_evidence_once_receipt_exists(db_path: Path) -> None:
    with Ledger(db_path, max_job_log_bytes=1500) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        ledger.append_event(
            job.job_id, typ="lifecycle", message="destroyed", payload={"phase": "destroyed"}
        )
        ledger.upsert_receipt(job.job_id, lifecycle={"destroyed": True})
        _fill(ledger, job.job_id, 60)
        events = ledger.list_events(job.job_id)
        assert "lifecycle" not in [e.type for e in events]
        assert events[0].type == "gap"
        assert ledger.retained_event_bytes(job.job_id) <= 1500


def test_ordinary_events_still_prune_with_gap(db_path: Path) -> None:
    with Ledger(db_path, max_job_log_bytes=1500) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        _fill(ledger, job.job_id, 60)
        events = ledger.list_events(job.job_id)
        assert events[0].type == "gap"
        assert ledger.retained_event_bytes(job.job_id) <= 1500


# --- backups -------------------------------------------------------------------------


def test_backup_copies_ledger_and_keeps_last_n(db_path: Path, tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from ledger.backup import backup_ledger, main

    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
    dest = tmp_path / "backups"
    start = datetime(2026, 11, 27, tzinfo=timezone.utc)
    for day in range(5):
        backup_ledger(db_path, dest, keep=3, now=start + timedelta(days=day))
    kept = sorted(p.name for p in dest.glob("killhub-ledger-*.db"))
    assert kept == [
        "killhub-ledger-20261129T000000Z.db",
        "killhub-ledger-20261130T000000Z.db",
        "killhub-ledger-20261201T000000Z.db",
    ]
    with Ledger(dest / kept[-1]) as restored:
        assert restored.get_job(job.job_id) is not None
    assert not list(dest.glob("*.partial"))

    assert main(["--db", str(tmp_path / "missing.db"), "--dest", str(dest)]) == 1
    assert main(["--db", str(db_path), "--dest", str(dest), "--keep", "2"]) == 0
    assert len(list(dest.glob("killhub-ledger-*.db"))) == 2


def test_upsert_vuln_report_fills_missing_severity_and_title(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
        report = ledger.upsert_vuln_report(
            job.job_id, summary="s", findings=[{"id": "canary-1", "source": "canary"}], status="ok"
        )
        assert report["findings"] == [
            {"id": "canary-1", "source": "canary", "severity": "medium", "title": "canary-1"}
        ]


def test_verdict_identifies_non_github_git_target(tmp_path: Path) -> None:
    # The legacy input field also carries public URLs on other supported hosts.
    url = "https://gitlab.com/example/nested/project"
    with Ledger(tmp_path / "ledger.db") as ledger:
        job = ledger.create_job(url, env_ttl_seconds=60)
        ledger.finalize_job(job.job_id, status="failed", receipt={}, include_verdict=True)
        target = ledger.get_receipt(job.job_id)["dossier"]["detonation_verdict"]["target"]
        assert target["source_type"] == "git_repo"
        assert target["locator"] == url


def test_shared_sqlite_ledger_serializes_concurrent_writers(db_path):
    from concurrent.futures import ThreadPoolExecutor

    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)

        def append(i):
            ledger.append_event(job.job_id, typ="log", message=str(i), payload={})

        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(append, range(40)))
        events = ledger.list_events(job.job_id)
        assert [int(e.event_id) for e in events] == list(range(1, 42))
