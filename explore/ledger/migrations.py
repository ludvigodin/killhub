"""Versioned ledger migrations (DATABASE.md rule 6, D41).

`ledger_meta.schema_version` records the applied version. On open:

- fresh database      → create the current schema and stamp ``LATEST_VERSION``
- older database      → copy the file to ``<db>.pre-v<N>.bak`` and apply each
                        numbered migration in its own transaction
- newer than the code → refuse to open (an older build must not write a newer ledger)

To change the schema: append ``Migration(N + 1, "...", fn)`` to ``MIGRATIONS``
and update ``SCHEMA_SQL`` so fresh databases match the migrated shape. Keep
field names stable (DATABASE.md rule 6).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ledger.schema import SCHEMA_SQL


@dataclass(frozen=True)
class Migration:
    version: int
    description: str
    apply: Callable[[sqlite3.Connection], None]


class LedgerVersionError(RuntimeError):
    """The ledger on disk was written by a newer schema than this build knows."""


# v1 is the baseline created by SCHEMA_SQL; later versions are appended here.
MIGRATIONS: tuple[Migration, ...] = ()
BASELINE_VERSION = 1


def latest_version(migrations: Sequence[Migration] = MIGRATIONS) -> int:
    return max([BASELINE_VERSION, *(m.version for m in migrations)])


def _read_version(conn: sqlite3.Connection) -> int | None:
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ledger_meta'"
    ).fetchone()
    if not has_meta:
        has_jobs = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone()
        # Tables without metadata predate versioning: treat as the v1 baseline.
        return BASELINE_VERSION if has_jobs else None
    row = conn.execute("SELECT value FROM ledger_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return BASELINE_VERSION
    return int(row[0])


def _stamp(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('schema_version', ?)",
        (str(version),),
    )


def _backup(conn: sqlite3.Connection, db_path: Path, from_version: int) -> Path | None:
    if not db_path.exists() or str(db_path) == ":memory:":
        return None
    target = db_path.with_name(f"{db_path.name}.pre-v{from_version + 1}.bak")
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    return target


def migrate(
    conn: sqlite3.Connection,
    db_path: Path,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> int:
    """Bring the ledger to the latest schema version and return it."""
    ordered = sorted(migrations, key=lambda m: m.version)
    versions = [m.version for m in ordered]
    if len(set(versions)) != len(versions) or any(v <= BASELINE_VERSION for v in versions):
        raise ValueError("migration versions must be unique and greater than the baseline")
    target = latest_version(ordered)

    current = _read_version(conn)
    if current is not None and current > target:
        raise LedgerVersionError(
            f"ledger schema_version {current} is newer than this build supports ({target})"
        )

    if current is None:
        # Fresh database: SCHEMA_SQL already reflects the newest shape.
        conn.executescript(SCHEMA_SQL)
        conn.execute("INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('engine', 'sqlite')")
        _stamp(conn, target)
        return target

    # Existing database: never run the newest DDL over an old shape; only the
    # numbered migrations may change it. Legacy files may lack ledger_meta.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute("INSERT OR REPLACE INTO ledger_meta(key, value) VALUES ('engine', 'sqlite')")

    pending = [m for m in ordered if m.version > current]
    if pending:
        _backup(conn, db_path, current)
    for migration in pending:
        conn.execute("BEGIN IMMEDIATE")
        try:
            migration.apply(conn)
            _stamp(conn, migration.version)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    if not pending:
        _stamp(conn, current)
    return target if pending else current
