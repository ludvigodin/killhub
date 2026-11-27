"""Online SQLite ledger backup with retention.

    python -m ledger.backup --dest /var/lib/killhub/backups --keep 7

Uses SQLite's backup API, which is safe while the explore worker is writing
(WAL mode), then verifies the copy with ``PRAGMA integrity_check``. The ledger
path comes from ``--db`` or ``LEDGER_URL``.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from ledger.store import parse_sqlite_path

PREFIX = "killhub-ledger-"
SUFFIX = ".db"


def backup_ledger(db_path: Path, dest_dir: Path, *, keep: int, now: datetime | None = None) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not db_path.exists():
        raise FileNotFoundError(f"ledger not found: {db_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    target = dest_dir / f"{PREFIX}{stamp}{SUFFIX}"
    partial = target.with_name(target.name + ".partial")

    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(partial)
    try:
        src.backup(dst)
        result = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"backup integrity_check failed: {result}")
    finally:
        dst.close()
        src.close()
    partial.replace(target)
    target.chmod(0o600)

    backups = sorted(dest_dir.glob(f"{PREFIX}*{SUFFIX}"))
    for old in backups[:-keep]:
        old.unlink()
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="ledger path (default: from LEDGER_URL)")
    parser.add_argument("--dest", required=True, help="backup directory")
    parser.add_argument("--keep", type=int, default=7, help="backups to retain (default 7)")
    args = parser.parse_args(argv)

    if args.db:
        db_path = Path(args.db)
    else:
        from config import get_settings

        db_path = parse_sqlite_path(get_settings().ledger_url)
    try:
        target = backup_ledger(db_path, Path(args.dest), keep=args.keep)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"ledger backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"ledger backup written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
