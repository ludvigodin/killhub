"""Plane 1 registry evidence storage with immutable release identity.

Pins are independent of runnable jobs. The unique registry identity makes
retries safe and prevents any caller from replacing an existing digest set.
"""

from __future__ import annotations

import json
from contextlib import closing
from uuid import uuid4

from config import Settings
from jobs import get_ledger
from ledger.db import Row, open_ledger_connection
from ledger.store import utc_now
from ledger.url import parse_ledger_url


class RegistryPinConflict(ValueError):
    """A registry release was previously recorded with different artifacts."""


def _read_pin(row: Row) -> dict:
    record = dict(row)
    record["artifacts"] = json.loads(record.pop("artifact_digests"))
    return record


def persist_registry_pin(release: dict, *, settings: Settings) -> dict:
    """Keep the first observed artifact set authoritative for a release."""
    get_ledger(settings)
    key = (release["registry"], release["package"], release["version"])
    digests = json.dumps(release["artifacts"], sort_keys=True, separators=(",", ":"))
    with closing(open_ledger_connection(parse_ledger_url(settings.ledger_url))) as conn, conn:
        # The unique key arbitrates concurrent writers across worker instances.
        conn.execute(
            """
            INSERT INTO registry_release_pins
                (pin_id, registry, package, version, artifact_digests, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (registry, package, version) DO NOTHING
            """,
            (str(uuid4()), *key, digests, utc_now()),
        )
        row = conn.execute(
            """
            SELECT * FROM registry_release_pins
            WHERE registry = ? AND package = ? AND version = ?
            """,
            key,
        ).fetchone()
        assert row is not None
        if row["artifact_digests"] != digests:
            raise RegistryPinConflict("Published digests differ from the recorded pin")
        return _read_pin(row)


def get_registry_pin(pin_id: str, *, settings: Settings) -> dict | None:
    """Read the pin from the durable ledger, even if the registry is offline."""
    get_ledger(settings)
    with closing(open_ledger_connection(parse_ledger_url(settings.ledger_url))) as conn:
        row = conn.execute(
            "SELECT * FROM registry_release_pins WHERE pin_id = ?", (pin_id,)
        ).fetchone()
    return None if row is None else _read_pin(row)
