"""Admission controls for job create (D40)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_queue_full_returns_503(
    client: TestClient, auth_header: dict[str, str], monkeypatch
) -> None:
    monkeypatch.setenv("MAX_CONCURRENT_JOBS", "1")
    monkeypatch.setenv("MAX_QUEUED_JOBS", "0")
    from config import get_settings

    get_settings.cache_clear()

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
