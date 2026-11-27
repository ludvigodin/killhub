"""Verify immutable Plane 1 registry pin storage against an actual SQLite ledger."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from config import Settings
from jobs import reset_ledger_for_tests
from ledger import Ledger
from ledger.registry_pins import RegistryPinConflict, get_registry_pin, persist_registry_pin


def test_pin_survives_restart_and_different_digest_is_rejected(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    release = {
        "registry": "pypi",
        "package": "demo",
        "version": "1.0",
        "artifacts": [{"filename": "demo.whl", "algorithm": "sha256", "digest": "a" * 64}],
    }
    try:
        saved = persist_registry_pin(release, settings=settings)
        reset_ledger_for_tests()
        assert get_registry_pin(saved["pin_id"], settings=settings) == saved
        assert persist_registry_pin(release, settings=settings) == saved
        different = {**release, "artifacts": [{**release["artifacts"][0], "digest": "b" * 64}]}
        with pytest.raises(RegistryPinConflict):
            persist_registry_pin(different, settings=settings)
        assert get_registry_pin(saved["pin_id"], settings=settings) == saved
    finally:
        reset_ledger_for_tests()


def test_existing_ledger_migrates_without_changing_job_rows(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with Ledger(path) as ledger:
        existing = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=60)

    # A v2 ledger has the checkout integrity table but no registry pin table.
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE registry_release_pins")
        connection.execute("UPDATE ledger_meta SET value = '2' WHERE key = 'schema_version'")

    with Ledger(path) as ledger:
        assert ledger.schema_version >= 3
        assert ledger.get_job(existing.job_id) == existing
    assert (tmp_path / "ledger.db.pre-v3.bak").is_file()


def test_registry_pin_requires_operator_api_auth(client: TestClient) -> None:
    response = client.post("/internal/registry/pins", json={"locator": "npm:demo@1.2.3"})
    assert response.status_code == 401
