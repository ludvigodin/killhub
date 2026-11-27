"""Shared Killhub operator MCP tools + JSON-RPC handlers (D81).

Used by stdio ``operator_mcp`` and HTTP ``POST /internal/mcp``.
Calls the **public** Jobs API at ``KILLHUB_BASE_URL`` so admission (D40) applies.
"""

from __future__ import annotations

import json
import os
import time
from contextvars import ContextVar
from typing import Any
from urllib.parse import urljoin

import httpx

from safety import review_priority

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
DEFAULT_BASE_URL = "https://killhub.pro"
DEFAULT_WAIT_TIMEOUT = 60.0
CREATE_AND_WAIT_TIMEOUT = 900.0
# Cap long polls on HTTP MCP so Next/Caddy proxies do not time out (D81).
HTTP_CREATE_AND_WAIT_TIMEOUT = 120.0
DEFAULT_POLL_SECONDS = 2.0
MAX_CREATE_JOBS = 5
FINDINGS_CAP = 10
MAX_TAIL_EVENTS = 200
DEFAULT_TAIL_EVENTS = 50

# Set True for public HTTP MCP requests (middleware / handle_jsonrpc http_mode).
mcp_http_mode: ContextVar[bool] = ContextVar("killhub_mcp_http_mode", default=False)

TOOL_NAMES = (
    "create_job",
    "create_jobs",
    "create_and_wait",
    "get_job",
    "get_job_status",
    "get_receipt",
    "list_jobs",
    "list_repos",
    "list_fixtures",
    "run_fixture",
    "cancel_job",
    "wait_job",
    "tail_events",
    "list_screenshots",
)


class KillhubApiError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def resolve_ui_url(base_url: str, job_id: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", f"jobs/{job_id}")


def absolute_api_url(base_url: str, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def summarize_status(snap: dict[str, Any], *, base_url: str) -> dict[str, Any]:
    job_id = str(snap.get("job_id") or "")
    status = str(snap.get("status") or "")
    return {
        "job_id": job_id,
        "status": status,
        "progress": snap.get("progress"),
        "current_step": snap.get("current_step"),
        "error": snap.get("error"),
        "ui_url": resolve_ui_url(base_url, job_id) if job_id else None,
        "done": status in TERMINAL_STATUSES,
    }


def summarize_receipt(snap: dict[str, Any], *, base_url: str) -> dict[str, Any]:
    status_bit = summarize_status(snap, base_url=base_url)
    verification = snap.get("verification")
    ver: dict[str, Any] | None = verification if isinstance(verification, dict) else None
    readiness = snap.get("readiness")
    ready: dict[str, Any] | None = readiness if isinstance(readiness, dict) else None

    findings: list[dict[str, Any]] = []
    vuln = snap.get("vuln_report")
    if isinstance(vuln, dict):
        raw = vuln.get("findings") or vuln.get("items") or []
        if isinstance(raw, list):
            ranked = sorted((f for f in raw if isinstance(f, dict)), key=review_priority)
            for item in ranked[:FINDINGS_CAP]:
                findings.append(
                    {
                        "id": item.get("id") or item.get("finding_id"),
                        "source": item.get("source"),
                        "package": item.get("package"),
                        "advisory_url": item.get("advisory_url"),
                        "severity": item.get("severity"),
                        "title": item.get("title") or item.get("summary"),
                    }
                )

    containment = None
    receipt = snap.get("receipt")
    if isinstance(receipt, dict):
        containment = receipt.get("containment")
        if containment is None and isinstance(receipt.get("dossier"), dict):
            containment = receipt["dossier"].get("containment")
    if containment is None and isinstance(snap.get("containment"), dict):
        containment = snap.get("containment")

    shot_ids = snap.get("screenshot_ids") or []
    if not isinstance(shot_ids, list):
        shot_ids = []

    return {
        **status_bit,
        "verification": {
            "kind": (ver or {}).get("kind"),
            "original_failure": (ver or {}).get("original_failure"),
        }
        if ver
        else None,
        "readiness": {
            "passed": ready.get("passed"),
            "detail": ready.get("detail") or ready.get("probe"),
        }
        if ready
        else None,
        "active_checks": ((receipt or {}).get("dossier") or {}).get("active_checks"),
        "scan_status": vuln.get("status") if isinstance(vuln, dict) else None,
        "vuln_review": (
            "Historical report with unknown dependency scan coverage."
            if isinstance(vuln, dict)
            and vuln.get("summary")
            == "No scan findings. Clean bill for this job's scanned surfaces."
            else vuln.get("summary")
            if isinstance(vuln, dict)
            else None
        ),
        "mcp_assessment": vuln.get("mcp_assessment") if isinstance(vuln, dict) else None,
        "finding_count": len(ranked) if isinstance(vuln, dict) and isinstance(raw, list) else None,
        "findings": findings,
        "containment": containment,
        "screenshot_ids": shot_ids,
        "screenshot_count": len(shot_ids),
        "resolved_commit": snap.get("resolved_commit"),
    }


def load_public_fixtures(client: KillhubJobsClient) -> list[dict[str, Any]]:
    return client.fixture_catalog()["fixtures"]


def resolve_public_fixture(name: str, client: KillhubJobsClient) -> dict[str, Any]:
    for fixture in load_public_fixtures(client):
        if fixture["id"] == name.strip():
            return fixture
    raise KillhubApiError(f"unknown or non-public fixture: {name}")


def parse_screenshot_resource_uri(uri: str) -> tuple[str, str] | None:
    prefix = "killhub://jobs/"
    if not uri.startswith(prefix):
        return None
    rest = uri[len(prefix) :]
    parts = rest.split("/")
    if len(parts) != 3 or parts[1] != "screenshots" or not parts[0] or not parts[2]:
        return None
    return parts[0], parts[2]


def screenshot_resource_uri(job_id: str, shot_id: str) -> str:
    return f"killhub://jobs/{job_id}/screenshots/{shot_id}"


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

    def fixture_catalog(self) -> dict[str, Any]:
        return self._request("GET", "/api/fixtures")

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

    def list_recent_events(
        self, job_id: str, *, limit: int = DEFAULT_TAIL_EVENTS
    ) -> dict[str, Any]:
        data = self._request(
            "GET",
            f"/api/jobs/{job_id}/events/recent",
            params={"limit": limit},
        )
        if not isinstance(data, dict):
            raise KillhubApiError(
                "list_recent_events: expected object response",
                body=data,
            )
        return data

    def list_screenshots(self, job_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/api/jobs/{job_id}/screenshots")
        if not isinstance(data, list):
            raise KillhubApiError("list_screenshots: expected array response", body=data)
        return data

    def wait_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = DEFAULT_WAIT_TIMEOUT,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        sleep: Any = time.sleep,
    ) -> dict[str, Any]:
        """Poll until terminal or soft timeout.

        Returns a full snapshot when terminal (``done`` via summarize), or the
        last snapshot when the soft timeout elapses (caller summarizes).
        """
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        last: dict[str, Any] | None = None
        while True:
            last = self.get_job(job_id)
            status = str(last.get("status") or "")
            if status in TERMINAL_STATUSES:
                return last
            if time.monotonic() >= deadline:
                return last
            sleep(max(0.1, poll_seconds))


def tools_list() -> list[dict[str, Any]]:
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
            "name": "create_jobs",
            "description": (
                f"Create up to {MAX_CREATE_JOBS} jobs from public git URLs. "
                "Returns per-URL job_id or error."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "github_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": MAX_CREATE_JOBS,
                    },
                },
                "required": ["github_urls"],
                "additionalProperties": False,
            },
        },
        {
            "name": "create_and_wait",
            "description": (
                "Create a job and poll until completed|failed|cancelled "
                f"(stdio default {int(CREATE_AND_WAIT_TIMEOUT)}s; "
                f"HTTP MCP capped at {int(HTTP_CREATE_AND_WAIT_TIMEOUT)}s). "
                "Over HTTP prefer create_job + wait_job to avoid proxy timeouts. "
                "Returns a slim receipt summary (or in-progress status if soft timeout)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "github_url": {"type": "string"},
                    "timeout_seconds": {
                        "type": "number",
                        "minimum": 1,
                        "default": CREATE_AND_WAIT_TIMEOUT,
                    },
                    "poll_seconds": {
                        "type": "number",
                        "minimum": 0.1,
                        "default": DEFAULT_POLL_SECONDS,
                    },
                },
                "required": ["github_url"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_job",
            "description": (
                "Fetch the full verbose job snapshot (profile, readiness, receipt). "
                "Prefer get_job_status / get_receipt for agents."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_job_status",
            "description": "Slim job status: progress, current_step, done, ui_url.",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_receipt",
            "description": (
                "Slim intake receipt: scan status and review, active-check coverage, "
                "highest-severity findings, verification.kind, readiness, "
                "screenshots, ui_url. Safe mid-job (null fields)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
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
            "name": "list_fixtures",
            "description": "List public M7 fixture ids usable with run_fixture.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "run_fixture",
            "description": ("Create a job for a pinned fixture offered by this deployment."),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "A fixture id from list_fixtures.",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        {
            "name": "cancel_job",
            "description": "Cancel a job and destroy its sandbox (idempotent).",
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "wait_job",
            "description": (
                f"Poll until terminal or soft timeout (default {int(DEFAULT_WAIT_TIMEOUT)}s). "
                "Returns slim status; done=false if still running."
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
        {
            "name": "tail_events",
            "description": "Last N durable job events (newest window, ascending order).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TAIL_EVENTS,
                        "default": DEFAULT_TAIL_EVENTS,
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "list_screenshots",
            "description": (
                "List screenshot ids/urls for a job. "
                "Resource URI: killhub://jobs/{job_id}/screenshots/{shot_id}."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"job_id": {"type": "string"}},
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
    ]


def _format_screenshots(
    client: KillhubJobsClient,
    job_id: str,
    shots: list[dict[str, Any]],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for shot in shots:
        shot_id = str(shot.get("screenshot_id") or shot.get("id") or "")
        if not shot_id:
            continue
        raw_url = shot.get("url") or shot.get("screenshot_url")
        if not raw_url:
            raw_url = f"/api/jobs/{job_id}/screenshots/{shot_id}"
        items.append(
            {
                "shot_id": shot_id,
                "url": absolute_api_url(client.base_url, str(raw_url)),
                "step": shot.get("step"),
                "resource_uri": screenshot_resource_uri(job_id, shot_id),
            }
        )
    return {"job_id": job_id, "screenshots": items}


def call_tool(client: KillhubJobsClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "create_job":
        url = str(arguments.get("github_url") or "").strip()
        if not url:
            raise KillhubApiError("github_url is required")
        return client.create_job(url)

    if name == "create_jobs":
        urls = arguments.get("github_urls")
        if not isinstance(urls, list) or not urls:
            raise KillhubApiError("github_urls must be a non-empty array")
        if len(urls) > MAX_CREATE_JOBS:
            raise KillhubApiError(f"github_urls max is {MAX_CREATE_JOBS}")
        jobs: list[dict[str, Any]] = []
        for raw in urls:
            github_url = str(raw or "").strip()
            if not github_url:
                jobs.append({"github_url": raw, "error": "empty url"})
                continue
            try:
                created = client.create_job(github_url)
                jobs.append({"github_url": github_url, "job_id": created.get("job_id")})
            except KillhubApiError as exc:
                entry: dict[str, Any] = {"github_url": github_url, "error": str(exc)}
                if exc.status_code is not None:
                    entry["status_code"] = exc.status_code
                jobs.append(entry)
        return {"jobs": jobs}

    if name == "create_and_wait":
        url = str(arguments.get("github_url") or "").strip()
        if not url:
            raise KillhubApiError("github_url is required")
        http_mode = mcp_http_mode.get() or (
            os.environ.get("KILLHUB_MCP_TRANSPORT", "").strip().lower() == "http"
        )
        default_timeout = HTTP_CREATE_AND_WAIT_TIMEOUT if http_mode else CREATE_AND_WAIT_TIMEOUT
        timeout = float(arguments.get("timeout_seconds") or default_timeout)
        if http_mode:
            timeout = min(timeout, HTTP_CREATE_AND_WAIT_TIMEOUT)
        poll = float(arguments.get("poll_seconds") or DEFAULT_POLL_SECONDS)
        created = client.create_job(url)
        job_id = str(created.get("job_id") or "")
        if not job_id:
            raise KillhubApiError("create_and_wait: missing job_id", body=created)
        snap = client.wait_job(job_id, timeout_seconds=timeout, poll_seconds=poll)
        if str(snap.get("status") or "") in TERMINAL_STATUSES:
            return summarize_receipt(snap, base_url=client.base_url)
        return summarize_status(snap, base_url=client.base_url)

    if name == "get_job":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        return client.get_job(job_id)

    if name == "get_job_status":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        return summarize_status(client.get_job(job_id), base_url=client.base_url)

    if name == "get_receipt":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        return summarize_receipt(client.get_job(job_id), base_url=client.base_url)

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

    if name == "list_fixtures":
        return client.fixture_catalog()

    if name == "run_fixture":
        fixture = resolve_public_fixture(str(arguments.get("name") or ""), client)
        created = client.create_job(str(fixture["github_url"]))
        return {
            "fixture": fixture["id"],
            "github_url": fixture["github_url"],
            "job_id": created.get("job_id"),
            "expected_intent": fixture.get("expected_intent"),
            "verification_kind": fixture.get("verification_kind"),
        }

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
        snap = client.wait_job(job_id, timeout_seconds=timeout, poll_seconds=poll)
        if str(snap.get("status") or "") in TERMINAL_STATUSES:
            return summarize_receipt(snap, base_url=client.base_url)
        return summarize_status(snap, base_url=client.base_url)

    if name == "tail_events":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        limit = int(arguments.get("limit") or DEFAULT_TAIL_EVENTS)
        limit = max(1, min(MAX_TAIL_EVENTS, limit))
        return client.list_recent_events(job_id, limit=limit)

    if name == "list_screenshots":
        job_id = str(arguments.get("job_id") or "").strip()
        if not job_id:
            raise KillhubApiError("job_id is required")
        shots = client.list_screenshots(job_id)
        # Build absolute URLs from shot ids when the list omits url fields.
        return _format_screenshots(client, job_id, list(shots))

    raise KillhubApiError(f"unknown tool: {name}")


def read_screenshot_resource(client: KillhubJobsClient, uri: str) -> dict[str, Any]:
    parsed = parse_screenshot_resource_uri(uri)
    if parsed is None:
        raise KillhubApiError(f"unsupported resource uri: {uri}")
    job_id, shot_id = parsed
    path = f"/api/jobs/{job_id}/screenshots/{shot_id}"
    url = absolute_api_url(client.base_url, path)
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "text/uri-list",
                "text": url,
            }
        ]
    }


def handle_jsonrpc(
    client: KillhubJobsClient,
    msg: dict[str, Any],
    *,
    http_mode: bool | None = None,
) -> dict[str, Any] | None:
    """Handle one JSON-RPC request. Returns None for notifications."""
    if http_mode is None:
        http_mode = os.environ.get("KILLHUB_MCP_TRANSPORT", "").strip().lower() == "http"
    mode_token = mcp_http_mode.set(bool(http_mode))
    try:
        return _handle_jsonrpc_body(client, msg)
    finally:
        mcp_http_mode.reset(mode_token)


def _handle_jsonrpc_body(client: KillhubJobsClient, msg: dict[str, Any]) -> dict[str, Any] | None:
    req_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    if method == "notifications/initialized" or (
        isinstance(method, str) and method.startswith("notifications/")
    ):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "killhub", "version": "0.2"},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": tools_list()},
        }

    if method == "tools/call":
        name = str(params.get("name") or "")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        try:
            if name not in TOOL_NAMES:
                raise KillhubApiError(f"unknown tool: {name}")
            result = call_tool(client, name, args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result)}],
                },
            }
        except KillhubApiError as exc:
            payload: dict[str, Any] = {"error": str(exc)}
            if exc.status_code is not None:
                payload["status_code"] = exc.status_code
            if exc.body is not None:
                payload["body"] = exc.body
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                },
            }
        except Exception as exc:  # noqa: BLE001 — surface to MCP client
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    if method == "resources/list":
        # Screenshots are discovered via list_screenshots tool (job-scoped).
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"resources": []},
        }

    if method == "resources/templates/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "resourceTemplates": [
                    {
                        "uriTemplate": "killhub://jobs/{job_id}/screenshots/{shot_id}",
                        "name": "job_screenshot",
                        "description": "Public URL for a job screenshot (text/uri-list)",
                        "mimeType": "text/uri-list",
                    }
                ]
            },
        }

    if method == "resources/read":
        uri = str(params.get("uri") or "")
        try:
            result = read_screenshot_resource(client, uri)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except KillhubApiError as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32002, "message": str(exc)},
            }

    if req_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return None


def client_from_env() -> KillhubJobsClient:
    base = (os.environ.get("KILLHUB_BASE_URL") or DEFAULT_BASE_URL).strip()
    token = (os.environ.get("KILLHUB_API_TOKEN") or "").strip() or None
    return KillhubJobsClient(base, token=token)
