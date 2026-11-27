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
        json={"github_url": "https://gitlab.com/org/repo"},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_url"


def test_health_unauthenticated(client: TestClient) -> None:
    res = client.get("/internal/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["ledger"]["engine"] == "sqlite"


def test_worker_stub_claims_pending(client: TestClient, auth_header: dict[str, str]) -> None:
    from service import claim_pending_job

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

    snap = client.get(f"/internal/jobs/{job_id}", headers=auth_header).json()
    assert snap["status"] == "analyzing"
