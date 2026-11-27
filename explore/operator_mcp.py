"""Operator-facing Killhub MCP (stdio) — wraps the public Jobs API (D81).

Distinct from ``harness_mcp`` (Environment Agent → Plane 2). This process is for
Cursor / Claude / other MCP clients that want to create and watch Killhub jobs
without the browser.

Env:
  KILLHUB_BASE_URL   default https://killhub.pro  (local: http://127.0.0.1:3000)
  KILLHUB_API_TOKEN  optional Bearer token (unused on anonymous public demo)
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any
from urllib.parse import urljoin

import httpx

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
DEFAULT_BASE_URL = "https://killhub.pro"
DEFAULT_WAIT_TIMEOUT = 900.0
DEFAULT_POLL_SECONDS = 2.0

TOOL_NAMES = (
    "create_job",
    "get_job",
    "list_jobs",
    "list_repos",
    "cancel_job",
    "wait_job",
)


class KillhubApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class KillhubJobsClient:
    """Thin HTTP client against Plane 1 public ``/api/*`` routes."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> KillhubJobsClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path.lstrip("/")
        try:
            resp = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise KillhubApiError(f"HTTP transport error: {exc}") from exc
        content_type = resp.headers.get("content-type", "")
        body: Any
        if "application/json" in content_type:
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text}
        else:
            body = {"raw": resp.text}
        if resp.status_code >= 400:
            detail = body if isinstance(body, dict) else {"body": body}
            msg = detail.get("error") or detail.get("detail") or resp.reason_phrase
            raise KillhubApiError(
                f"{method} {url} → {resp.status_code}: {msg}",
                status_code=resp.status_code,
                body=detail,
            )
        return body

    def create_job(self, github_url: str) -> dict[str, Any]:
        data = self._request("POST", "/api/jobs", json={"github_url": github_url})
        if not isinstance(data, dict):
            raise KillhubApiError("create_job: expected object response", body=data)
        return data

    def get_job(self, job_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/api/jobs/{job_id}")
        if not isinstance(data, dict):
            raise KillhubApiError("get_job: expected object response", body=data)
        return data

    def list_jobs(
        self,
        *,
        limit: int = 48,
        offset: int = 0,
        github_url: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if github_url:
            params["github_url"] = github_url
        data = self._request("GET", "/api/jobs", params=params)
        if not isinstance(data, dict):
            raise KillhubApiError("list_jobs: expected object response", body=data)
        return data

    def list_repos(self, *, limit: int = 48, offset: int = 0) -> dict[str, Any]:
        data = self._request("GET", "/api/repos", params={"limit": limit, "offset": offset})
        if not isinstance(data, dict):
            raise KillhubApiError("list_repos: expected object response", body=data)
        return data

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        data = self._request("DELETE", f"/api/jobs/{job_id}")
        if not isinstance(data, dict):
            raise KillhubApiError("cancel_job: expected object response", body=data)
        return data

    def wait_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = DEFAULT_WAIT_TIMEOUT,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        sleep: Any = time.sleep,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        last: dict[str, Any] | None = None
        while True:
            last = self.get_job(job_id)
            status = str(last.get("status") or "")
            if status in TERMINAL_STATUSES:
                return last
            if time.monotonic() >= deadline:
                raise KillhubApiError(
                    f"wait_job timed out after {timeout_seconds}s (status={status or 'unknown'})",
                    body=last,
                )
            sleep(max(0.1, poll_seconds))


def _tools_list() -> list[dict[str, Any]]:
    return [
        {
            "name": "create_job",
            "description": (
                "Start a Killhub job for a public HTTPS git URL "
                "(github.com / gitlab.com / bitbucket.org / codeberg.org). "
                "Returns { job_id }."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "github_url": {
                        "type": "string",
                        "description": "Public allowlisted git HTTPS URL",
                    },
                },
                "required": ["github_url"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_job",
            "description": "Fetch the full job snapshot (status, profile, readiness, receipt).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_jobs",
            "description": "List recent job summaries (newest first). Optional github_url filter.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 48},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "github_url": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "list_repos",
            "description": "List distinct repos with their latest run (home feed grouping).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 48},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "cancel_job",
            "description": "Cancel a job and destroy its sandbox (idempotent).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "wait_job",
            "description": (
                "Poll get_job until status is completed|failed|cancelled or timeout. "
                "Returns the final snapshot."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "timeout_seconds": {
                        "type": "number",
                        "minimum": 1,
                        "default": DEFAULT_WAIT_TIMEOUT,
                    },
                    "poll_seconds": {
                        "type": "number",
                        "minimum": 0.1,
                        "default": DEFAULT_POLL_SECONDS,
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
    ]


def call_tool(client: KillhubJobsClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "create_job":
        url = str(arguments.get("github_url") or "").strip()
        if not url:
            raise KillhubApiError("github_url is required")
        return client.create_job(url)
    if name == "get_job":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        return client.get_job(job_id)
    if name == "list_jobs":
        limit = int(arguments.get("limit") or 48)
        offset = int(arguments.get("offset") or 0)
        github_url = arguments.get("github_url")
        github = str(github_url).strip() if github_url else None
        return client.list_jobs(limit=limit, offset=offset, github_url=github or None)
    if name == "list_repos":
        limit = int(arguments.get("limit") or 48)
        offset = int(arguments.get("offset") or 0)
        return client.list_repos(limit=limit, offset=offset)
    if name == "cancel_job":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        return client.cancel_job(job_id)
    if name == "wait_job":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        timeout = float(arguments.get("timeout_seconds") or DEFAULT_WAIT_TIMEOUT)
        poll = float(arguments.get("poll_seconds") or DEFAULT_POLL_SECONDS)
        return client.wait_job(job_id, timeout_seconds=timeout, poll_seconds=poll)
    raise KillhubApiError(f"unknown tool: {name}")


def _read_message() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _client_from_env() -> KillhubJobsClient:
    base = (os.environ.get("KILLHUB_BASE_URL") or DEFAULT_BASE_URL).strip()
    token = (os.environ.get("KILLHUB_API_TOKEN") or "").strip() or None
    return KillhubJobsClient(base, token=token)


def main() -> int:
    client = _client_from_env()
    try:
        while True:
            msg = _read_message()
            if msg is None:
                break
            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params") or {}

            if method == "initialize":
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "killhub", "version": "0.1"},
                        },
                    }
                )
                continue
            if method == "notifications/initialized":
                continue
            if method == "tools/list":
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {"tools": _tools_list()},
                    }
                )
                continue
            if method == "tools/call":
                name = str(params.get("name") or "")
                args = params.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                try:
                    if name not in TOOL_NAMES:
                        raise KillhubApiError(f"unknown tool: {name}")
                    result = call_tool(client, name, args)
                    _write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": json.dumps(result)},
                                ]
                            },
                        }
                    )
                except KillhubApiError as exc:
                    payload: dict[str, Any] = {"error": str(exc)}
                    if exc.status_code is not None:
                        payload["status_code"] = exc.status_code
                    if exc.body is not None:
                        payload["body"] = exc.body
                    _write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "result": {
                                "isError": True,
                                "content": [
                                    {"type": "text", "text": json.dumps(payload)},
                                ],
                            },
                        }
                    )
                except Exception as exc:  # noqa: BLE001 — surface to MCP client
                    _write_message(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32000, "message": str(exc)},
                        }
                    )
                continue
            if req_id is not None:
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32601, "message": f"method not found: {method}"},
                    }
                )
    finally:
        client.close()
    return 0


def resolve_ui_url(base_url: str, job_id: str) -> str:
    """Helper for docs/tests — browser URL for a job."""
    return urljoin(base_url.rstrip("/") + "/", f"jobs/{job_id}")


if __name__ == "__main__":
    raise SystemExit(main())
