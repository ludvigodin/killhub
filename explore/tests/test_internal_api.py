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


def test_create_from_pinned_fixture(client: TestClient, auth_header: dict[str, str]) -> None:
    from fixtures import match_fixture, require_fixture

    response = client.post(
        "/internal/jobs", headers=auth_header, json={"fixture_id": "sca_npm_control"}
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]
    snapshot = client.get(f"/internal/jobs/{job_id}", headers=auth_header).json()
    fixture = require_fixture("sca_npm_control")
    assert snapshot["github_url"] == fixture["github_url"]
    assert match_fixture(snapshot["github_url"])["commit"] == fixture["commit"]
    assert snapshot["sandbox_id"] is None


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"fixture_id": "unregistered"}, "invalid_fixture"),
        ({"fixture_id": "webapp_image_replace"}, "invalid_fixture"),
        (
            {"fixture_id": "webapp_success", "github_url": "https://github.com/example/repo"},
            "invalid_target",
        ),
    ],
)
def test_rejected_fixture_selectors_create_no_job(
    client: TestClient, auth_header: dict[str, str], payload: dict[str, str], code: str
) -> None:
    response = client.post("/internal/jobs", headers=auth_header, json=payload)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == code
    assert client.get("/internal/jobs", headers=auth_header).json()["total"] == 0


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

    # Streamable HTTP: no GET stream on this endpoint (D81 handshake fix).
    info = client.get("/internal/mcp", headers=auth_header)
    assert info.status_code == 405
    assert info.headers.get("allow", "").upper().find("POST") >= 0

    note = client.post(
        "/internal/mcp",
        headers=auth_header,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert note.status_code == 202
    assert note.content in (b"", b"null") or note.text in ("", "null")


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


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/org/repo.git",
        "https://bitbucket.org/org/repo",
        "https://codeberg.org/org/repo",
    ],
)
def test_reject_legacy_git_hosts_at_intake(
    client: TestClient, auth_header: dict[str, str], url: str
) -> None:
    res = client.post(
        "/internal/jobs",
        headers=auth_header,
        json={"github_url": url},
    )
    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "invalid_url"
    jobs = client.get("/internal/jobs", headers=auth_header)
    assert jobs.status_code == 200
    assert jobs.json()["total"] == 0


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

    # Pretend a pipeline is configured without enabling the background runner's
    # real discover/install path (would race the TestClient worker loop).
    monkeypatch.setattr("service._pipeline_flags_enabled", lambda _cfg: True)
    monkeypatch.setattr("worker._run_claimed_job", lambda *_a, **_k: None)
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


def test_claim_without_pipeline_flags_skips(
    client: TestClient, auth_header: dict[str, str], monkeypatch
) -> None:
    from config import get_settings
    from service import claim_pending_job

    # Default claim flags are off — do not claim into a stub (D83).
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
        assert snap["status"] == "pending"
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
