"""Internal Worker API + cancel ordering + SSE cursor tests (D52, D55, D61)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_auth_required(client: TestClient) -> None:
    res = client.post("/internal/jobs", json={"github_url": "https://github.com/a/b"})
    assert res.status_code == 401


def test_create_snapshot_sse_cancel_flow(client: TestClient, auth_header: dict[str, str]) -> None:
    create = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    assert create.status_code == 201
    job_id = create.json()["job_id"]

    snap = client.get(f"/internal/jobs/{job_id}", headers=auth_header)
    assert snap.status_code == 200
    body = snap.json()
    assert body["job_id"] == job_id
    assert body["event_cursor"] == "1"
    assert body["status"] == "pending"
    assert body["screenshot_ids"] == []

    cancel = client.delete(f"/internal/jobs/{job_id}", headers=auth_header)
    assert cancel.status_code == 200
    cancelled = cancel.json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested_at"] is not None
    assert cancelled["receipt"] is not None
    assert cancelled["cleanup"]["status"] == "destroyed"
    assert cancelled["destroyed_at"] is not None

    # Replay SSE from the beginning of the retained window.
    with client.stream(
        "GET",
        f"/internal/jobs/{job_id}/events",
        headers=auth_header,
    ) as stream:
        assert stream.status_code == 200
        statuses: list[str] = []
        for line in stream.iter_lines():
            if not line.startswith("data:"):
                continue
            payload = json.loads(line.removeprefix("data:").strip())
            status = payload.get("status") or (payload.get("payload") or {}).get("status")
            if status:
                statuses.append(status)
            if status == "cancelled":
                break
        assert "cancelled" in statuses

    # Idempotent cancel.
    again = client.delete(f"/internal/jobs/{job_id}", headers=auth_header)
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"
    assert again.json()["receipt"] is not None


def test_ordinary_writers_rejected_after_cancel(
    client: TestClient, auth_header: dict[str, str]
) -> None:
    from jobs import get_ledger
    from ledger import Ledger

    create = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/modelcontextprotocol/servers"},
    )
    job_id = create.json()["job_id"]
    client.delete(f"/internal/jobs/{job_id}", headers=auth_header)

    ledger = get_ledger()
    try:
        ledger.append_event(job_id, typ="log", message="should fail")
        raise AssertionError("ordinary append should be frozen")
    except Ledger.WriterFrozenError:
        pass


def test_events_recent_last_n(client: TestClient, auth_header: dict[str, str]) -> None:
    from jobs import get_ledger

    create = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    job_id = create.json()["job_id"]
    ledger = get_ledger()
    for i in range(5):
        ledger.append_event(job_id, typ="log", message=f"m{i}", payload={"i": i})

    res = client.get(
        f"/internal/jobs/{job_id}/events/recent",
        headers=auth_header,
        params={"limit": 3},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["job_id"] == job_id
    assert len(body["events"]) == 3
    expected = ledger.list_events(job_id)[-3:]
    assert [e["message"] for e in body["events"]] == [e.message for e in expected]
    ids = [int(e["event_id"]) for e in body["events"]]
    assert ids == sorted(ids)


def test_operator_mcp_initialize(client: TestClient, auth_header: dict[str, str]) -> None:
    res = client.post(
        "/internal/mcp",
        headers=auth_header,
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["result"]["serverInfo"]["name"] == "killhub"

    info = client.get("/internal/mcp", headers=auth_header)
    assert info.status_code == 200
    assert info.json()["transport"] == "json-rpc"


def test_cursor_expired_returns_410(client: TestClient, auth_header: dict[str, str]) -> None:
    create = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://github.com/heroku/node-js-getting-started"},
    )
    job_id = create.json()["job_id"]
    res = client.get(
        f"/internal/jobs/{job_id}/events",
        headers=auth_header,
        params={"after": "999999"},
    )
    assert res.status_code == 410
    assert res.json()["code"] == "cursor_expired"


def test_invalid_github_url(client: TestClient, auth_header: dict[str, str]) -> None:
    res = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://example.com/org/repo"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_url"


def test_accept_gitlab_url(client: TestClient, auth_header: dict[str, str], monkeypatch) -> None:
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    from config import get_settings

    get_settings.cache_clear()
    res = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": "https://gitlab.com/org/repo.git"},
    )
    assert res.status_code == 201
    job_id = res.json()["job_id"]
    snap = client.get(f"/internal/jobs/{job_id}", headers=auth_header).json()
    assert snap["github_url"] == "https://gitlab.com/org/repo"
    get_settings.cache_clear()


def test_health_unauthenticated(client: TestClient) -> None:
    res = client.get("/internal/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["ledger"]["engine"] == "sqlite"


def test_worker_claims_pending_when_pipeline_enabled(
    client: TestClient, auth_header: dict[str, str], monkeypatch
) -> None:
    from config import get_settings
    from service import claim_pending_job

    monkeypatch.setenv("DISCOVER_ON_CLAIM", "true")
    get_settings.cache_clear()
    try:
        create = client.post(
            "/internal/jobs",
            headers=auth_header,
            json={"github_url": "https://github.com/heroku/node-js-getting-started"},
        )
        job_id = create.json()["job_id"]

        claimed = claim_pending_job()
        assert claimed is not None
        assert claimed.job_id == job_id
        assert claimed.status == "analyzing"
        assert claimed.current_step == "analyzing"

        snap = client.get(f"/internal/jobs/{job_id}", headers=auth_header).json()
        assert snap["status"] == "analyzing"
    finally:
        get_settings.cache_clear()


def test_claim_without_pipeline_flags_fails(
    client: TestClient, auth_header: dict[str, str], monkeypatch
) -> None:
    from config import get_settings
    from service import claim_pending_job

    # Default claim flags are off — claiming must fail closed (D81).
    for key in (
        "MSB_AUTO_CREATE",
        "DISCOVER_ON_CLAIM",
        "INSTALL_ON_CLAIM",
        "VERIFY_ON_CLAIM",
        "SCREENSHOTS_ON_CLAIM",
        "CONTAINMENT_ON_CLAIM",
        "FINALIZE_ON_CLAIM",
    ):
        monkeypatch.setenv(key, "false")
    get_settings.cache_clear()
    try:
        create = client.post(
            "/internal/jobs",
            headers=auth_header,
            json={"github_url": "https://github.com/heroku/node-js-getting-started"},
        )
        job_id = create.json()["job_id"]

        claimed = claim_pending_job()
        assert claimed is None

        snap = client.get(f"/internal/jobs/{job_id}", headers=auth_header).json()
        assert snap["status"] == "failed"
        assert snap["receipt"]["dossier"]["code"] == "worker_misconfigured"
    finally:
        get_settings.cache_clear()


def test_failed_ledger_health_returns_503(client, monkeypatch):
    def unavailable(*args):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr("jobs.get_ledger", unavailable)
    response = client.get("/internal/health")
    assert response.status_code == 503
    assert response.json()["ledger"]["ok"] is False


def test_fixture_catalog_matches_restricted_admission(client, auth_header, monkeypatch):
    from config import get_settings

    monkeypatch.setenv("PUBLIC_DEMO_FIXTURES_ONLY", "true")
    get_settings.cache_clear()
    try:
        res = client.get("/internal/fixtures", headers=auth_header)
        assert res.status_code == 200
        catalog = res.json()
        assert catalog["restricted"] is True
        assert {entry["id"] for entry in catalog["fixtures"]} == {
            "sca_python_affected",
            "sca_npm_control",
            "sca_npm_affected",
        }
    finally:
        get_settings.cache_clear()


def test_operator_rpc_can_call_back_into_sidecar(client, auth_header, monkeypatch):
    import asyncio

    import pytest

    def dispatch(_client, body):
        with pytest.raises(RuntimeError, match="no running event loop"):
            asyncio.get_running_loop()
        # A synchronous public API call requires another request on the same event loop.
        nested = client.get("/internal/fixtures", headers=auth_header)
        assert nested.status_code == 200
        return {"jsonrpc": "2.0", "id": body["id"], "result": nested.json()}

    monkeypatch.setattr("operator_mcp_tools.handle_jsonrpc", dispatch)
    response = client.post("/internal/mcp", headers=auth_header, json={"id": 1})
    assert response.status_code == 200
    assert response.json()["result"]["fixtures"]
