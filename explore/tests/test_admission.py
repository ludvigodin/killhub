"""Admission controls for job create (D40 / D71)."""

from __future__ import annotations

import fakeredis
from fastapi.testclient import TestClient

from admission import reset_admission_store_for_tests
from admission.valkey import ValkeyAdmissionStore


def test_queue_full_returns_503(
    client: TestClient, auth_header: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("MAX_QUEUED_JOBS", "0")
    from config import get_settings

    get_settings.cache_clear()
    reset_admission_store_for_tests()

    first = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    assert first.status_code == 201

    second = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/modelcontextprotocol/servers"},
    )
    assert second.status_code == 503
    assert second.json()["detail"]["code"] == "queue_full"

    get_settings.cache_clear()
    reset_admission_store_for_tests()


def test_valkey_queue_full_via_store(
    client: TestClient, auth_header: dict[str, str], monkeypatch
) -> None:
    """Concurrency counters come from Valkey when ADMISSION_STORE=valkey."""
    monkeypatch.setenv("ADMISSION_STORE", "valkey")
    monkeypatch.setenv("VALKEY_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("MAX_QUEUED_JOBS", "0")
    import admission.factory as factory
    from config import get_settings

    get_settings.cache_clear()
    reset_admission_store_for_tests()
    fake = fakeredis.FakeRedis(decode_responses=True)
    factory._store = ValkeyAdmissionStore(fake)

    first = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    assert first.status_code == 201

    second = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/modelcontextprotocol/servers"},
    )
    assert second.status_code == 503
    assert second.json()["detail"]["code"] == "queue_full"

    reset_admission_store_for_tests()
    get_settings.cache_clear()
