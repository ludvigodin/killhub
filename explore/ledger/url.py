"""Parse ``LEDGER_URL`` into a ledger target (SQLite path or Postgres DSN)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

LedgerEngine = Literal["sqlite", "postgres"]


@dataclass(frozen=True)
class LedgerTarget:
    """Resolved ledger backend from ``LEDGER_URL``."""

    engine: LedgerEngine
    # Filesystem path when engine == "sqlite"
    path: Path | None = None
    # libpq/psycopg connection string when engine == "postgres"
    dsn: str | None = None


def parse_sqlite_path(ledger_url: str) -> Path:
    """Resolve SQLAlchemy-style SQLite URLs to a filesystem path.

    - ``sqlite:///relative.db`` → cwd-relative
    - ``sqlite:////abs/path.db`` → absolute ``/abs/path.db``
    """
    target = parse_ledger_url(ledger_url)
    if target.engine != "sqlite" or target.path is None:
        raise ValueError(f"LEDGER_URL is not a sqlite:// URL: {ledger_url}")
    return target.path


def parse_ledger_url(ledger_url: str) -> LedgerTarget:
    """Parse ``LEDGER_URL`` into a ``LedgerTarget``.

    Supported schemes:

    - ``sqlite:///…`` — local durable file (default for local/dev)
    - ``postgresql://…`` / ``postgres://…`` — hosted Postgres (Vultr Managed DB)

    Raises ``ValueError`` with a clear message for empty, unknown, or malformed URLs.
    """
    raw = (ledger_url or "").strip()
    if not raw:
        raise ValueError("LEDGER_URL is empty")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()

    if scheme == "sqlite":
        return LedgerTarget(engine="sqlite", path=_sqlite_path_from_url(raw))

    if scheme in {"postgresql", "postgres"}:
        if not parsed.hostname:
            raise ValueError(f"Invalid Postgres LEDGER_URL (missing host): {ledger_url}")
        # Keep the original URL for psycopg/libpq (incl. sslmode query params).
        # Normalize postgres:// → postgresql:// for consistency.
        dsn = raw
        if scheme == "postgres":
            dsn = "postgresql://" + raw[len("postgres://") :]
        return LedgerTarget(engine="postgres", dsn=dsn)

    if scheme:
        raise ValueError(
            f"Unsupported LEDGER_URL scheme {scheme!r}; "
            "use sqlite:// or postgresql:// (postgres://)"
        )
    raise ValueError(f"Invalid LEDGER_URL: {ledger_url}")


def _sqlite_path_from_url(ledger_url: str) -> Path:
    prefix = "sqlite://"
    if not ledger_url.startswith(prefix):
        raise ValueError(f"Invalid LEDGER_URL: {ledger_url}")

    rest = ledger_url[len(prefix) :]
    if rest.startswith("//"):
        # sqlite:////abs/path → rest="//abs/path"
        return Path(unquote(rest[1:])).resolve()
    if rest.startswith("/"):
        # sqlite:///relative → rest="/relative"
        path = Path(unquote(rest[1:]))
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()
    raise ValueError(f"Invalid LEDGER_URL: {ledger_url}")
