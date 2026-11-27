"""Shared fixtures for explore tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import jobs
from admission import reset_admission_store_for_tests
from config import get_settings

TOKEN = "test-internal-token"


@pytest.fixture(autouse=True)
def _isolate_deployment_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Keep the suite offline-stable when explore/.env points at live VX1 storage.

    pydantic Settings loads ``env_file=".env"`` from cwd. explore/.env is a
    symlink to the deployment dotenv, so delenv falls through to live s3/CDN.
    Run each test with a cwd that has no .env (PRODUCT_FIXES §6).
    """
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    monkeypatch.setenv("STORAGE_BACKEND", "filesystem")
    monkeypatch.setenv("OBJECT_STORAGE_CDN_BASE_URL", "")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "")
    monkeypatch.setenv("LEDGER_BACKUP_UPLOAD", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db = tmp_path / "ledger" / "test.db"
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("SSE_KEEPALIVE_SECONDS", "1")
    monkeypatch.setenv("WORKER_POLL_SECONDS", "0.2")
    monkeypatch.setenv("ENV_TTL_SECONDS", "3600")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("DISCOVER_ON_CLAIM", "false")
    monkeypatch.setenv("INSTALL_ON_CLAIM", "false")
    monkeypatch.setenv("VERIFY_ON_CLAIM", "false")
    monkeypatch.setenv("SCREENSHOTS_ON_CLAIM", "false")
    monkeypatch.setenv("CONTAINMENT_ON_CLAIM", "false")
    monkeypatch.setenv("FINALIZE_ON_CLAIM", "false")
    monkeypatch.setenv("ADMISSION_STORE", "memory")
    # Preflight has dedicated tests; default suite stays offline-stable.
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    get_settings.cache_clear()
    reset_admission_store_for_tests()
    jobs.reset_ledger_for_tests()

    from main import app

    with TestClient(app) as test_client:
        yield test_client

    jobs.reset_ledger_for_tests()
    reset_admission_store_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
