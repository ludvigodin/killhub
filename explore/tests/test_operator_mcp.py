"""Operator MCP (D81) — Jobs API client + tool dispatch (no live network)."""

from __future__ import annotations

import json

import httpx
import pytest

from operator_mcp import (
    KillhubApiError,
    KillhubJobsClient,
    call_tool,
    resolve_ui_url,
)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_create_and_get_job_roundtrip() -> None:
    jobs: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/jobs":
            body = json.loads(request.content.decode())
            assert body["github_url"].startswith("https://github.com/")
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
        snap = call_tool(client, "get_job", {"job_id": "job-1"})
        assert snap["status"] == "queued"


def test_list_jobs_and_repos_pass_query_params() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/api/jobs":
            return httpx.Response(
                200,
                json={"jobs": [], "total": 0, "limit": 12, "offset": 0},
            )
        if request.url.path == "/api/repos":
            return httpx.Response(
                200,
                json={"repos": [], "total": 0, "limit": 9, "offset": 3},
            )
        return httpx.Response(404, json={"error": "nope"})

    with KillhubJobsClient("http://127.0.0.1:3000", transport=_transport(handler)) as client:
        call_tool(
            client,
            "list_jobs",
            {
                "limit": 12,
                "offset": 0,
                "github_url": "https://github.com/org/repo",
            },
        )
        call_tool(client, "list_repos", {"limit": 9, "offset": 3})

    assert "limit=12" in seen[0]
    assert "github_url=" in seen[0]
    assert "offset=3" in seen[1]


def test_cancel_job() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/api/jobs/abc"
        return httpx.Response(200, json={"job_id": "abc", "status": "cancelled"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        out = call_tool(client, "cancel_job", {"job_id": "abc"})
        assert out["status"] == "cancelled"


def test_wait_job_reaches_terminal() -> None:
    ticks = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        ticks["n"] += 1
        status = "installing" if ticks["n"] < 3 else "completed"
        return httpx.Response(
            200,
            json={"job_id": "j1", "status": status, "progress": ticks["n"] * 30},
        )

    sleeps: list[float] = []

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        out = client.wait_job(
            "j1",
            timeout_seconds=10,
            poll_seconds=0.01,
            sleep=sleeps.append,
        )
    assert out["status"] == "completed"
    assert len(sleeps) == 2


def test_wait_job_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "j1", "status": "installing"})

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        with pytest.raises(KillhubApiError, match="timed out"):
            client.wait_job(
                "j1",
                timeout_seconds=0.05,
                poll_seconds=0.02,
                sleep=lambda _s: None,
            )


def test_api_error_surfaces_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": "too many", "code": "rate_limited"},
        )

    with KillhubJobsClient("https://killhub.pro", transport=_transport(handler)) as client:
        with pytest.raises(KillhubApiError) as ei:
            call_tool(client, "create_job", {"github_url": "https://github.com/a/b"})
        assert ei.value.status_code == 429
        assert ei.value.body["code"] == "rate_limited"


def test_unknown_tool() -> None:
    transport = _transport(lambda _r: httpx.Response(200))
    with KillhubJobsClient("https://killhub.pro", transport=transport) as client:
        with pytest.raises(KillhubApiError, match="unknown tool"):
            call_tool(client, "explode", {})


def test_resolve_ui_url() -> None:
    assert resolve_ui_url("https://killhub.pro", "abc") == "https://killhub.pro/jobs/abc"
