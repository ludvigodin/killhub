"""Versioned ledger migrations (DATABASE.md rule 6, D41, D73).

``ledger_meta.schema_version`` records the applied version. On open:

- fresh database      → create the current schema and stamp ``LATEST_VERSION``
- older database      → apply each numbered migration in its own transaction
                        (SQLite also copies the file to ``<db>.pre-v<N>.bak``)
- newer than the code → refuse to open (an older build must not write a newer ledger)

To change the schema: append ``Migration(N + 1, "...", fn)`` to ``MIGRATIONS``
and update ``SCHEMA_SQL`` / ``SCHEMA_SQL_POSTGRES`` so fresh databases match
the migrated shape. Keep field names stable (DATABASE.md rule 6).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ledger.db import SqliteConnection, upsert_meta_sql, wrap_connection
from ledger.schema import CHECKOUT_INTEGRITY_SQL, REGISTRY_PINS_SQL, SCHEMA_SQL, SCHEMA_SQL_POSTGRES
from ledger.url import LedgerEngine


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[Any], None]


class LedgerVersionError(RuntimeError):
    """The ledger was written by a newer schema than this build knows."""


BASELINE_VERSION = 1


def _add_checkout_integrity(conn: Any) -> None:
    """Add nullable evidence for live generations without rewriting older rows."""
    conn.execute(CHECKOUT_INTEGRITY_SQL)


def _add_registry_pins(conn: Any) -> None:
    """Record immutable registry evidence independently of runnable jobs."""
    conn.execute(REGISTRY_PINS_SQL)


MIGRATIONS = (
    Migration(2, "sandbox checkout digests", _add_checkout_integrity),
    Migration(3, "registry release pins", _add_registry_pins),
)


def latest_version(migrations: Sequence[Migration] = MIGRATIONS) -> int:
    return max([BASELINE_VERSION, *(m.version for m in migrations)])


def _read_version(conn: Any, engine: LedgerEngine) -> int | None:
    if engine == "sqlite":
        has_meta = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ledger_meta'"
        ).fetchone()
        if not has_meta:
            has_jobs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
            ).fetchone()
            # Tables without metadata predate versioning: treat as the v1 baseline.
            return BASELINE_VERSION if has_jobs else None
    else:
        has_meta = conn.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'ledger_meta'
            """
        ).fetchone()
        if not has_meta:
            has_jobs = conn.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'jobs'
                """
            ).fetchone()
            return BASELINE_VERSION if has_jobs else None

    row = conn.execute(
        "SELECT value FROM ledger_meta WHERE key = ?",
        ("schema_version",),
    ).fetchone()
    if row is None:
        return BASELINE_VERSION
    return int(row["value"] if isinstance(row, dict) else row[0])


def _stamp(conn: Any, version: int) -> None:
    conn.execute(upsert_meta_sql(), ("schema_version", str(version)))


def _stamp_engine(conn: Any, engine: LedgerEngine) -> None:
    conn.execute(upsert_meta_sql(), ("engine", engine))


def _backup_sqlite(conn: Any, db_path: Path | None, from_version: int) -> Path | None:
    if db_path is None or not db_path.exists() or str(db_path) == ":memory:":
        return None
    target = db_path.with_name(f"{db_path.name}.pre-v{from_version + 1}.bak")
    if isinstance(conn, SqliteConnection):
        conn.backup_to(target)
        return target
    # Raw sqlite3.Connection (unit tests / legacy callers).
    dest = sqlite3.connect(target)
    try:
        raw = conn._conn if hasattr(conn, "_conn") else conn
        raw.backup(dest)
    finally:
        dest.close()
    return target


def migrate(
    conn: Any,
    db_path: Path | None = None,
    migrations: Sequence[Migration] = MIGRATIONS,
    *,
    engine: LedgerEngine = "sqlite",
) -> int:
    """Bring the ledger to the latest schema version and return it."""
    db = wrap_connection(conn, engine=engine, db_path=db_path)
    eng: LedgerEngine = getattr(db, "engine", engine)

    ordered = sorted(migrations, key=lambda m: m.version)
    versions = [m.version for m in ordered]
    if len(set(versions)) != len(versions) or any(v <= BASELINE_VERSION for v in versions):
        raise ValueError("migration versions must be unique and greater than the baseline")
    target = latest_version(ordered)

    current = _read_version(db, eng)
    if current is not None and current > target:
        raise LedgerVersionError(
            f"ledger schema_version {current} is newer than this build supports ({target})"
        )

    if current is None:
        # Fresh database: SCHEMA already reflects the newest shape.
        ddl = SCHEMA_SQL if eng == "sqlite" else SCHEMA_SQL_POSTGRES
        db.executescript(ddl)
        _stamp_engine(db, eng)
        _stamp(db, target)
        return target

    # Existing database: never run the newest DDL over an old shape; only the
    # numbered migrations may change it. Legacy files may lack ledger_meta.
    db.execute("CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    _stamp_engine(db, eng)

    pending = [m for m in ordered if m.version > current]
    if pending and eng == "sqlite":
        _backup_sqlite(db, db_path, current)
    for migration in pending:
        db.begin()
        try:
            migration.apply(db)
            _stamp(db, migration.version)
            db.commit()
        except Exception:
            db.rollback()
            raise
    if not pending:
        _stamp(db, current)
    return target if pending else current
