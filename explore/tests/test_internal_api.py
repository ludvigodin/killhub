"""Internal Worker API + cancel ordering + SSE cursor tests (D52, D55, D61)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import routes
from ledger import Ledger


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
    # Verdicts become available with the terminal receipt, including on cancel.
    verdict_url = f"/internal/jobs/{job_id}/verdict"
    unavailable = client.get(verdict_url, headers=auth_header)
    assert unavailable.status_code == 404
    assert unavailable.json()["detail"]["code"] == "verdict_not_ready"

    cancel = client.delete(f"/internal/jobs/{job_id}", headers=auth_header)
    assert cancel.status_code == 200
    cancelled = cancel.json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested_at"] is not None
    assert cancelled["receipt"] is not None
    assert cancelled["cleanup"]["status"] == "destroyed"
    assert cancelled["destroyed_at"] is not None
    assert client.get(verdict_url).status_code == 401
    verdict = client.get(verdict_url, headers=auth_header)
    assert verdict.status_code == 200
    assert verdict.json() == cancelled["detonation_verdict"]
    assert verdict.json() == cancelled["receipt"]["dossier"]["detonation_verdict"]
    assert verdict.json()["verdict"]["status"] == "ABORTED"
    assert verdict.json()["target"]["package_sha256_before"] is None

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


def test_live_sse_progress_and_keepalive(tmp_path: Path) -> None:
    """A progress event published after an empty poll should reach the client promptly."""
    with Ledger(tmp_path / "events.db") as ledger:
        job = ledger.create_job("https://github.com/a/b", env_ttl_seconds=60)
        progress = {"progress": 40, "current_step": "installing"}

        async def publish() -> None:
            # Give the live tail at least one empty poll before publishing.
            await asyncio.sleep(2.1)
            ledger.append_event(job.job_id, typ="progress", message="installing", payload=progress)

        async def read_stream() -> None:
            stream = routes._event_stream(
                ledger, job.job_id, after=job.event_cursor, keepalive_seconds=4
            )
            publisher = asyncio.create_task(publish())
            try:
                event = await asyncio.wait_for(anext(stream), timeout=3.8)
                assert event.startswith("id: 2\nevent: progress\n")
                live = json.loads(event.split("data: ", 1)[1])
                assert live["progress"] == 40
                assert live["current_step"] == "installing"
                assert await asyncio.wait_for(anext(stream), timeout=6) == ": keepalive\n\n"
                ledger.finalize_job(job.job_id, status="completed", receipt={})
                assert "event: status\n" in await asyncio.wait_for(anext(stream), timeout=2)
                with pytest.raises(StopAsyncIteration):
                    await anext(stream)
            finally:
                await publisher
                await stream.aclose()

        asyncio.run(read_stream())


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
