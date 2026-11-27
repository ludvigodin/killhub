"""Shared fixtures for explore tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import jobs
from config import get_settings

TOKEN = "test-internal-token"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db = tmp_path / "ledger" / "test.db"
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("SSE_KEEPALIVE_SECONDS", "1")
    monkeypatch.setenv("WORKER_POLL_SECONDS", "0.2")
    monkeypatch.setenv("ENV_TTL_SECONDS", "3600")
    get_settings.cache_clear()
    jobs.reset_ledger_for_tests()

    from main import app

    with TestClient(app) as test_client:
        yield test_client

    jobs.reset_ledger_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}
