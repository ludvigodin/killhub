"""Ledger migrations, receipt-before-terminal (D61), vuln reports and protected pruning (D67)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ledger import Ledger
from ledger.migrations import LedgerVersionError, Migration, latest_version, migrate

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


def test_pending_migrations_apply_in_order_with_backup(db_path: Path) -> None:
    with Ledger(db_path) as ledger:
        job = ledger.create_job(URL, env_ttl_seconds=60)
    baseline = latest_version()

    applied: list[int] = []
    next_a = baseline + 1
    next_b = baseline + 2

    def add_column(conn: sqlite3.Connection) -> None:
        applied.append(next_a)
        conn.execute("ALTER TABLE jobs ADD COLUMN target_type TEXT NOT NULL DEFAULT 'github_repo'")

    def add_index(conn: sqlite3.Connection) -> None:
        applied.append(next_b)
        conn.execute("CREATE INDEX idx_jobs_status ON jobs(status)")

    migrations = [
        Migration(next_b, "index", add_index),
        Migration(next_a, "column", add_column),
    ]
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        assert migrate(conn, db_path, migrations) == next_b
        row = conn.execute(
            "SELECT target_type FROM jobs WHERE job_id = ?", (job.job_id,)
        ).fetchone()
    finally:
        conn.close()

    assert applied == [next_a, next_b]
    assert row is not None
    assert row[0] == "github_repo"
    assert _meta(db_path, "schema_version") == str(next_b)
    backup = db_path.with_name(f"{db_path.name}.pre-v{next_a}.bak")
    assert backup.exists()
    with sqlite3.connect(backup) as bconn:
        assert bconn.execute("SELECT value FROM ledger_meta WHERE key='schema_version'").fetchone()[
            0
        ] == str(baseline)


def test_failed_migration_rolls_back_and_keeps_version(db_path: Path) -> None:
    Ledger(db_path).close()
    baseline = latest_version()

    def boom(conn: sqlite3.Connection) -> None:
        conn.execute("ALTER TABLE jobs ADD COLUMN half_done TEXT")
        raise RuntimeError("migration failed")

    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        with pytest.raises(RuntimeError, match="migration failed"):
            migrate(conn, db_path, [Migration(baseline + 1, "boom", boom)])
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    finally:
        conn.close()
    assert "half_done" not in cols
    assert _meta(db_path, "schema_version") == str(baseline)


def test_newer_ledger_is_refused(db_path: Path) -> None:
    Ledger(db_path).close()
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE ledger_meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(LedgerVersionError):
        Ledger(db_path)


_V1_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    github_url TEXT NOT NULL,
    resolved_commit TEXT,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    current_step TEXT NOT NULL DEFAULT '',
    steps_completed TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    readiness TEXT,
    verification TEXT,
    verify_result TEXT,
    sandbox_id TEXT,
    current_profile_revision INTEGER,
    current_sandbox_generation INTEGER,
    inference_model TEXT,
    inference_usage TEXT,
    event_cursor TEXT,
    expires_at TEXT NOT NULL,
    cleanup TEXT NOT NULL,
    destroyed_at TEXT,
    cancel_requested_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
    job_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    type TEXT NOT NULL,
    message TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    PRIMARY KEY (job_id, event_id)
);
"""


def test_legacy_ledger_without_meta_is_treated_as_v1_then_migrates(db_path: Path) -> None:
    """Pre-versioning DBs (no ledger_meta) are treated as v1, then real migrations apply."""
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_V1_JOBS_DDL)
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, github_url, status, progress, current_step,
                expires_at, cleanup, created_at, updated_at
            ) VALUES (
                'legacy-1', ?, 'pending', 0, 'accepted',
                '2099-01-01T00:00:00Z', '{"status":"pending","attempts":0}',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """,
            (URL,),
        )
    with Ledger(db_path) as ledger:
        assert ledger.schema_version == latest_version()
        job = ledger.get_job("legacy-1")
        assert job is not None
        assert job.git_url == URL
    assert _meta(db_path, "schema_version") == str(latest_version())
    with sqlite3.connect(db_path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert "git_url" in cols
    assert "github_url" not in cols


def test_rename_github_url_to_git_url_migration(db_path: Path) -> None:
    """v1 ledger with github_url becomes git_url at schema_version 2."""
    from ledger.migrations import MIGRATIONS

    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_V1_JOBS_DDL)
        conn.execute("CREATE TABLE ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO ledger_meta (key, value) VALUES ('schema_version', '1')")
        conn.execute("INSERT INTO ledger_meta (key, value) VALUES ('engine', 'sqlite')")
        conn.execute(
            """
            INSERT INTO jobs (
                job_id, github_url, status, progress, current_step,
                expires_at, cleanup, created_at, updated_at
            ) VALUES (
                'v1-job', ?, 'pending', 0, 'accepted',
                '2099-01-01T00:00:00Z', '{"status":"pending","attempts":0}',
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """,
            (URL,),
        )
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        assert migrate(conn, db_path, MIGRATIONS) == 2
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        row = conn.execute("SELECT git_url FROM jobs WHERE job_id = 'v1-job'").fetchone()
    finally:
        conn.close()
    assert "git_url" in cols and "github_url" not in cols
    assert row is not None and row[0] == URL
    assert _meta(db_path, "schema_version") == "2"


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
            {"id": "canary-1", "source": "canary", "severity": "unknown", "title": "canary-1"}
        ]
        preserved = ledger.upsert_vuln_report(
            job.job_id,
            summary="s",
            findings=[
                {
                    "id": "sca-1",
                    "source": "sca",
                    "severity": "unknown",
                    "title": "GHSA-xxxx",
                }
            ],
            status="partial",
        )
        assert preserved["findings"][0]["severity"] == "unknown"


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
