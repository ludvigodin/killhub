"""Online SQLite ledger backup with retention.

    python -m ledger.backup --dest /var/lib/killhub/backups --keep 7
    python -m ledger.backup --dest /var/lib/killhub/backups --keep 7 --upload

Uses SQLite's backup API, which is safe while the explore worker is writing
(WAL mode), then verifies the copy with ``PRAGMA integrity_check``. The ledger
path comes from ``--db`` or ``LEDGER_URL``.

Optional Object Storage upload (D72): when ``--upload`` or
``LEDGER_BACKUP_UPLOAD=true`` and Vultr Object Storage is configured, the
local snapshot is also stored under ``{prefix}/backups/ledger/`` with the
same retention count. Local backups always remain the primary path.

Postgres ``LEDGER_URL`` is not supported by this SQLite file-copy tool —
use Vultr Managed Database backups or ``pg_dump`` (D73).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ledger.url import parse_ledger_url, parse_sqlite_path

PREFIX = "killhub-ledger-"
SUFFIX = ".db"


def backup_ledger(
    db_path: Path,
    dest_dir: Path,
    *,
    keep: int,
    now: datetime | None = None,
    upload: bool = False,
    settings: Any | None = None,
    object_client: Any | None = None,
) -> Path:
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

    if upload:
        _upload_backup(
            target,
            keep=keep,
            settings=settings,
            object_client=object_client,
        )
    return target


def _upload_backup(
    target: Path,
    *,
    keep: int,
    settings: Any | None = None,
    object_client: Any | None = None,
) -> str:
    from object_storage import (
        object_storage_config,
        prune_prefix,
        require_object_storage_config,
        upload_file,
    )

    cfg = settings
    if cfg is None:
        from config import get_settings

        cfg = get_settings()
    require_object_storage_config(cfg)
    ref = upload_file(
        target,
        kind="backup",
        filename=target.name,
        content_type="application/x-sqlite3",
        settings=cfg,
        client=object_client,
    )
    conf = object_storage_config(cfg)
    prefix = f"{conf.prefix}/backups/ledger/"
    prune_prefix(prefix, keep=keep, settings=cfg, client=object_client)
    return ref


def _should_upload(cli_upload: bool, settings: Any | None = None) -> bool:
    if cli_upload:
        return True
    cfg = settings
    if cfg is None:
        from config import get_settings

        cfg = get_settings()
    return bool(getattr(cfg, "ledger_backup_upload", False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="ledger path (default: from LEDGER_URL)")
    parser.add_argument("--dest", required=True, help="backup directory")
    parser.add_argument("--keep", type=int, default=7, help="backups to retain (default 7)")
    parser.add_argument(
        "--upload",
        action="store_true",
        help="also upload to Vultr Object Storage (or set LEDGER_BACKUP_UPLOAD=true)",
    )
    args = parser.parse_args(argv)

    if args.db:
        db_path = Path(args.db)
    else:
        from config import get_settings

        ledger_url = get_settings().ledger_url
        target = parse_ledger_url(ledger_url)
        if target.engine != "sqlite":
            print(
                "ledger backup failed: LEDGER_URL is Postgres; "
                "use Vultr Managed Database backups or pg_dump (D73)",
                file=sys.stderr,
            )
            return 1
        db_path = parse_sqlite_path(ledger_url)
    try:
        from config import get_settings

        settings = get_settings()
        upload = _should_upload(args.upload, settings)
        target = backup_ledger(
            db_path,
            Path(args.dest),
            keep=args.keep,
            upload=upload,
            settings=settings,
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"ledger backup failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — surface ObjectStorageError etc.
        from object_storage import ObjectStorageError

        if isinstance(exc, ObjectStorageError):
            print(f"ledger backup upload failed: {exc}", file=sys.stderr)
            return 1
        print(f"ledger backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"ledger backup written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
