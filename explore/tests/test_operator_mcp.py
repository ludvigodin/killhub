"""Operator MCP (D81) — reducers, tools, soft wait, fixtures, resources."""

from __future__ import annotations

import json

import httpx
import pytest

from operator_mcp_tools import (
    MAX_CREATE_JOBS,
    KillhubApiError,
    KillhubJobsClient,
    call_tool,
    handle_jsonrpc,
    load_public_fixtures,
    parse_screenshot_resource_uri,
    read_screenshot_resource,
    resolve_public_fixture,
    resolve_ui_url,
    summarize_receipt,
    summarize_status,
)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_summarize_status_and_receipt() -> None:
    snap = {
        "job_id": "j1",
        "status": "completed",
        "progress": 100,
        "current_step": "done",
        "error": None,
        "verification": {"kind": "original_application", "original_failure": None},
        "readiness": {"passed": True, "detail": "ok"},
        "vuln_report": {
            "findings": [
                {"id": "f1", "source": "sca", "severity": "high", "title": "CVE"},
            ]
        },
        "receipt": {"containment": {"claim": "incomplete"}},
        "screenshot_ids": ["s1"],
        "resolved_commit": "abc",
    }
    status = summarize_status(snap, base_url="https://killhub.pro")
    assert status["done"] is True
    assert status["ui_url"] == "https://killhub.pro/jobs/j1"
    receipt = summarize_receipt(snap, base_url="https://killhub.pro/")
    assert receipt["verification"]["kind"] == "original_application"
    assert receipt["findings"][0]["id"] == "f1"
    assert receipt["screenshot_count"] == 1
    assert receipt["containment"]["claim"] == "incomplete"


def test_create_and_get_job_roundtrip() -> None:
    jobs: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/jobs":
            body = json.loads(request.content.decode())
            job_id = "job-1"
            jobs[job_id] = {
                "job_id": job_id,
                "github_url": body["github_url"],
                "status": "queued",
                "progress": 0,
            }
            return httpx.Response(201, json={"job_id": job_id})
        if request.method == "GET" and request.url.path == "/api/jobs/job-1":
            return httpx.Response(200, json=jobs["job-1"])
        return httpx.Response(404, json={"error": "not found", "code": "not_found"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        created = call_tool(
            client,
            "create_job",
            {"github_url": "https://github.com/heroku/nodejs-getting-started"},
        )
        assert created == {"job_id": "job-1"}
        status = call_tool(client, "get_job_status", {"job_id": "job-1"})
        assert status["status"] == "queued"
        assert status["done"] is False


def test_wait_job_soft_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "j1", "status": "installing", "progress": 10})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        out = call_tool(
            client,
            "wait_job",
            {"job_id": "j1", "timeout_seconds": 0.05, "poll_seconds": 0.02},
        )
    assert out["done"] is False
    assert out["status"] == "installing"


def test_wait_job_terminal_returns_receipt() -> None:
    ticks = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        ticks["n"] += 1
        status = "installing" if ticks["n"] < 2 else "completed"
        return httpx.Response(
            200,
            json={
                "job_id": "j1",
                "status": status,
                "progress": 100 if status == "completed" else 40,
                "verification": {"kind": "original_application"},
                "readiness": {"passed": True},
                "screenshot_ids": [],
            },
        )

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        out = call_tool(
            client,
            "wait_job",
            {"job_id": "j1", "timeout_seconds": 5, "poll_seconds": 0.01},
        )
    assert out["done"] is True
    assert out["verification"]["kind"] == "original_application"


def test_create_and_wait() -> None:
    state = {"created": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            state["created"] = True
            return httpx.Response(201, json={"job_id": "j9"})
        return httpx.Response(
            200,
            json={
                "job_id": "j9",
                "status": "completed",
                "progress": 100,
                "verification": {"kind": "generated_demo", "original_failure": "boom"},
                "readiness": {"passed": True},
                "screenshot_ids": [],
            },
        )

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        out = call_tool(
            client,
            "create_and_wait",
            {
                "github_url": "https://github.com/org/repo",
                "timeout_seconds": 5,
                "poll_seconds": 0.01,
            },
        )
    assert state["created"] is True
    assert out["job_id"] == "j9"
    assert out["verification"]["kind"] == "generated_demo"


def test_create_jobs_cap_and_partial_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        url = body["github_url"]
        if "bad" in url:
            return httpx.Response(400, json={"error": "nope", "code": "invalid_url"})
        return httpx.Response(201, json={"job_id": "ok-1"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        out = call_tool(
            client,
            "create_jobs",
            {
                "github_urls": [
                    "https://github.com/a/b",
                    "https://github.com/bad/repo",
                ]
            },
        )
        assert out["jobs"][0]["job_id"] == "ok-1"
        assert "error" in out["jobs"][1]
        with pytest.raises(KillhubApiError, match=str(MAX_CREATE_JOBS)):
            call_tool(
                client,
                "create_jobs",
                {"github_urls": [f"https://github.com/a/{i}" for i in range(MAX_CREATE_JOBS + 1)]},
            )


@pytest.mark.parametrize("restricted", [False, True])
def test_fixtures_catalog_and_run(restricted: bool) -> None:
    from fixtures import intake_catalog

    catalog = intake_catalog(restricted=restricted)
    fixture = catalog["fixtures"][0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/fixtures":
            return httpx.Response(200, json=catalog)
        assert json.loads(request.content)["github_url"] == fixture["github_url"]
        return httpx.Response(201, json={"job_id": "fix-1"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        assert load_public_fixtures(client) == catalog["fixtures"]
        assert call_tool(client, "list_fixtures", {}) == catalog
        assert call_tool(client, "run_fixture", {"name": fixture["id"]})["job_id"] == "fix-1"
        with pytest.raises(KillhubApiError, match="non-public"):
            resolve_public_fixture("webapp_image_replace", client)
        if restricted:
            with pytest.raises(KillhubApiError, match="non-public"):
                resolve_public_fixture("webapp_success", client)


def test_tail_events_and_screenshots() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/events/recent"):
            assert "limit=2" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "job_id": "j1",
                    "limit": 2,
                    "events": [
                        {"event_id": "1", "type": "log", "message": "a", "payload": {}},
                        {"event_id": "2", "type": "progress", "message": "b", "payload": {}},
                    ],
                },
            )
        if request.url.path.endswith("/screenshots"):
            return httpx.Response(
                200,
                json=[{"screenshot_id": "shot-a", "step": "ready"}],
            )
        return httpx.Response(404, json={"error": "nope"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        events = call_tool(client, "tail_events", {"job_id": "j1", "limit": 2})
        assert len(events["events"]) == 2
        shots = call_tool(client, "list_screenshots", {"job_id": "j1"})
        assert shots["screenshots"][0]["shot_id"] == "shot-a"
        assert shots["screenshots"][0]["url"].endswith("/api/jobs/j1/screenshots/shot-a")
        assert shots["screenshots"][0]["resource_uri"] == "killhub://jobs/j1/screenshots/shot-a"


def test_resources_read_and_jsonrpc() -> None:
    assert parse_screenshot_resource_uri("killhub://jobs/j1/screenshots/s1") == ("j1", "s1")
    assert parse_screenshot_resource_uri("https://x") is None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        contents = read_screenshot_resource(client, "killhub://jobs/j1/screenshots/s1")
        assert contents["contents"][0]["text"].endswith("/api/jobs/j1/screenshots/s1")

        init = handle_jsonrpc(client, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert init is not None
        assert init["result"]["serverInfo"]["name"] == "killhub"

        listed = handle_jsonrpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        names = {t["name"] for t in listed["result"]["tools"]}
        assert "create_and_wait" in names
        assert "tail_events" in names

        templates = handle_jsonrpc(
            client, {"jsonrpc": "2.0", "id": 3, "method": "resources/templates/list"}
        )
        assert templates is not None
        assert templates["result"]["resourceTemplates"]

        read = handle_jsonrpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {"uri": "killhub://jobs/j1/screenshots/s1"},
            },
        )
        assert read is not None
        assert "contents" in read["result"]


def test_list_jobs_and_cancel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"job_id": "abc", "status": "cancelled"})
        return httpx.Response(200, json={"jobs": [], "total": 0, "limit": 12, "offset": 0})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        call_tool(client, "list_jobs", {"limit": 12})
        out = call_tool(client, "cancel_job", {"job_id": "abc"})
        assert out["status"] == "cancelled"


def test_api_error_and_unknown_tool() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "too many", "code": "rate_limited"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        with pytest.raises(KillhubApiError) as ei:
            call_tool(client, "create_job", {"github_url": "https://github.com/a/b"})
        assert ei.value.status_code == 429
        with pytest.raises(KillhubApiError, match="unknown tool"):
            call_tool(client, "explode", {})


def test_resolve_ui_url() -> None:
    assert resolve_ui_url("https://killhub.pro", "abc") == "https://killhub.pro/jobs/abc"
