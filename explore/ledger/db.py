"""Thin dialect adapters for the Plane 1 ledger (SQLite + PostgreSQL).

SQL in ``store.py`` / ``migrations.py`` keeps ``?`` placeholders. Adapters
translate to the driver dialect, manage explicit transactions, and expose
dict-like rows so callers stay engine-agnostic.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from ledger.url import LedgerEngine, LedgerTarget, parse_ledger_url

Row = Mapping[str, Any]


class CursorResult(Protocol):
    def fetchone(self) -> Row | None: ...

    def fetchall(self) -> list[Row]: ...


class DbConnection(Protocol):
    engine: LedgerEngine

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> CursorResult: ...

    def executescript(self, script: str) -> None: ...

    def begin(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...

    def backup_to(self, dest_path: Path) -> None: ...


_PARAM = re.compile(r"\?")


def qmark_to_percent(sql: str) -> str:
    """Replace ``?`` bind markers with ``%s`` (psycopg)."""
    return _PARAM.sub("%s", sql)


class _SqliteCursor:
    def __init__(self, cur: sqlite3.Cursor) -> None:
        self._cur = cur

    def fetchone(self) -> Row | None:
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[Row]:
        return [dict(r) for r in self._cur.fetchall()]


class SqliteConnection:
    """sqlite3 wrapper with the shared ledger connection surface."""

    engine: Literal["sqlite"] = "sqlite"

    def __init__(self, conn: sqlite3.Connection, *, db_path: Path | None = None) -> None:
        self._conn = conn
        self.db_path = db_path
        self._conn.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> SqliteConnection:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            path,
            isolation_level=None,  # manage transactions explicitly
            check_same_thread=False,
        )
        wrapper = cls(conn, db_path=path)
        wrapper.execute("PRAGMA foreign_keys = ON")
        wrapper.execute("PRAGMA journal_mode = WAL")
        wrapper.execute("PRAGMA busy_timeout = 5000")
        return wrapper

    @classmethod
    def from_existing(
        cls, conn: sqlite3.Connection, *, db_path: Path | None = None
    ) -> SqliteConnection:
        return cls(conn, db_path=db_path)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> CursorResult:
        cur = self._conn.execute(sql, tuple(params or ()))
        return _SqliteCursor(cur)

    def executescript(self, script: str) -> None:
        self._conn.executescript(script)

    def begin(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self._conn.execute("COMMIT")

    def rollback(self) -> None:
        self._conn.execute("ROLLBACK")

    def close(self) -> None:
        self._conn.close()

    def backup_to(self, dest_path: Path) -> None:
        dest = sqlite3.connect(dest_path)
        try:
            self._conn.backup(dest)
        finally:
            dest.close()

    def __enter__(self) -> SqliteConnection:
        self.begin()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


class _PgCursor:
    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def fetchone(self) -> Row | None:
        row = self._cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self) -> list[Row]:
        return [dict(r) for r in self._cur.fetchall()]


class PostgresConnection:
    """psycopg (v3) wrapper with the shared ledger connection surface."""

    engine: Literal["postgres"] = "postgres"

    def __init__(self, conn: Any, *, dsn: str) -> None:
        self._conn = conn
        self.dsn = dsn

    @classmethod
    def open(cls, dsn: str) -> PostgresConnection:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - fail-closed without driver
            raise RuntimeError(
                "PostgreSQL LEDGER_URL requires the psycopg package "
                "(pip install 'psycopg[binary]'). "
                f"Import failed: {exc}"
            ) from exc
        try:
            conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to connect to PostgreSQL ledger (check LEDGER_URL / TLS / firewall): {exc}"
            ) from exc
        return cls(conn, dsn=dsn)

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> CursorResult:
        cur = self._conn.execute(qmark_to_percent(sql), tuple(params or ()))
        return _PgCursor(cur)

    def executescript(self, script: str) -> None:
        for stmt in _split_sql_statements(script):
            self._conn.execute(stmt)

    def begin(self) -> None:
        self._conn.execute("BEGIN")

    def commit(self) -> None:
        self._conn.execute("COMMIT")

    def rollback(self) -> None:
        self._conn.execute("ROLLBACK")

    def close(self) -> None:
        self._conn.close()

    def backup_to(self, dest_path: Path) -> None:
        raise NotImplementedError(
            "File-copy ledger backups apply to SQLite only; "
            "use Vultr Managed Database backups or pg_dump for Postgres"
        )

    def __enter__(self) -> PostgresConnection:
        self.begin()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()


def open_ledger_connection(target: LedgerTarget) -> SqliteConnection | PostgresConnection:
    if target.engine == "sqlite":
        if target.path is None:
            raise ValueError("sqlite LedgerTarget missing path")
        return SqliteConnection.open(target.path)
    if target.engine == "postgres":
        if not target.dsn:
            raise ValueError("postgres LedgerTarget missing dsn")
        return PostgresConnection.open(target.dsn)
    raise ValueError(f"unsupported ledger engine: {target.engine}")


def open_from_url(ledger_url: str) -> SqliteConnection | PostgresConnection:
    return open_ledger_connection(parse_ledger_url(ledger_url))


def wrap_connection(
    conn: Any, *, engine: LedgerEngine = "sqlite", db_path: Path | None = None
) -> SqliteConnection | PostgresConnection:
    """Adapt a raw driver connection (used by migration unit tests)."""
    if isinstance(conn, (SqliteConnection, PostgresConnection)):
        return conn
    if isinstance(conn, sqlite3.Connection):
        return SqliteConnection.from_existing(conn, db_path=db_path)
    raise TypeError(f"cannot wrap connection of type {type(conn).__name__}")


def _split_sql_statements(script: str) -> Iterator[str]:
    """Split a multi-statement DDL script on semicolons (no nested procedures)."""
    buf: list[str] = []
    in_single = False
    in_double = False
    for ch in script:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
            continue
        if ch == ";" and not in_single and not in_double:
            stmt = "".join(buf).strip()
            buf = []
            if stmt:
                yield stmt
            continue
        buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        yield tail


def upsert_meta_sql() -> str:
    """Dialect-neutral ledger_meta upsert (``?`` placeholders)."""
    return """
    INSERT INTO ledger_meta(key, value) VALUES (?, ?)
    ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """


__all__ = [
    "CursorResult",
    "DbConnection",
    "PostgresConnection",
    "Row",
    "SqliteConnection",
    "open_from_url",
    "open_ledger_connection",
    "qmark_to_percent",
    "upsert_meta_sql",
    "wrap_connection",
]
