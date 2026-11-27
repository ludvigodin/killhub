"""Internal Worker API routes (D52, D55, D61)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api.auth import require_internal_token
from config import get_settings
from fixtures import intake_catalog, resolve_intake_fixture
from jobs import get_ledger
from ledger import Ledger
from ledger.store import validate_github_url
from novnc_bridge import console_metadata
from package_metadata import PackageMetadataError, resolve_package_metadata
from service import (
    AdmissionError,
    cancel_job,
    create_job,
    get_public_snapshot,
    list_jobs_page,
    list_repos_page,
)

router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_internal_token)],
)


class CreateJobBody(BaseModel):
    github_url: str | None = Field(default=None, min_length=1)
    fixture_id: str | None = Field(default=None, min_length=1, max_length=96)


def _error(status_code: int, message: str, code: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": message, "code": code},
    )


@router.get("/fixtures")
def get_fixture_catalog() -> dict[str, Any]:
    return intake_catalog(restricted=get_settings().public_demo_fixtures_only)


@router.get("/registry/resolve")
def get_registry_release(locator: str = Query(min_length=1, max_length=320)) -> dict:
    """Resolve release metadata without admitting a job or fetching an artifact."""
    try:
        with httpx.Client(timeout=4, trust_env=False) as client:
            return resolve_package_metadata(locator, client=client)
    except PackageMetadataError as exc:
        raise _error(exc.status, str(exc), exc.code) from exc


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def post_job(
    body: CreateJobBody,
    x_forwarded_for: Optional[str] = Header(default=None),
    x_real_ip: Optional[str] = Header(default=None),
    x_client_ip: Optional[str] = Header(default=None),
) -> Dict[str, str]:
    # Resolve fixture selection before admission so invalid selectors reserve no capacity.
    if (body.github_url is None) == (body.fixture_id is None):
        raise _error(400, "Provide one GitHub URL or fixture ID", "invalid_target")
    github_url = body.github_url
    if body.fixture_id is not None:
        try:
            github_url = resolve_intake_fixture(
                body.fixture_id, restricted=get_settings().public_demo_fixtures_only
            )
        except ValueError as exc:
            raise _error(400, str(exc), "invalid_fixture") from exc
    assert github_url is not None
    client_ip: Optional[str] = None
    if x_client_ip:
        client_ip = x_client_ip.strip()
    elif x_real_ip:
        client_ip = x_real_ip.strip()
    elif x_forwarded_for:
        client_ip = x_forwarded_for.split(",")[0].strip()
    try:
        job = create_job(github_url, client_ip=client_ip)
    except AdmissionError as exc:
        raise _error(exc.status_code, exc.message, exc.code) from exc
    except ValueError as exc:
        raise _error(400, str(exc), "invalid_url") from exc
    return {"job_id": job.job_id}


@router.get("/jobs")
def list_jobs(
    limit: int = Query(default=48, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    github_url: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Recent jobs newest-first (D69 / D77). Optional github_url filter (D79)."""
    filtered: Optional[str] = None
    if github_url is not None and github_url.strip():
        try:
            filtered = validate_github_url(github_url)
        except ValueError as exc:
            raise _error(400, str(exc), "invalid_url") from exc
    return list_jobs_page(limit=limit, offset=offset, github_url=filtered)


@router.get("/repos")
def list_repos(
    limit: int = Query(default=48, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Distinct github_url groups for the home feed (D79)."""
    return list_repos_page(limit=limit, offset=offset)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    snap = get_public_snapshot(job_id)
    if snap is None:
        raise _error(404, "job not found", "not_found")
    settings = get_settings()
    console = console_metadata(settings, get_ledger(settings), job_id)
    if console is not None:
        snap["novnc"] = console
    return snap


@router.get("/jobs/{job_id}/verdict")
def get_verdict(job_id: str) -> Dict[str, Any]:
    """Read the durable verdict. A legacy or unfinished job may be missing one."""
    ledger = get_ledger()
    if ledger.get_job(job_id) is None:
        raise _error(404, "job not found", "not_found")
    receipt = ledger.get_receipt(job_id) or {}
    verdict = (receipt.get("dossier") or {}).get("detonation_verdict")
    if verdict is None:
        raise _error(404, "verdict not yet available", "verdict_not_ready")
    return verdict


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> Dict[str, Any]:
    try:
        return cancel_job(job_id)
    except KeyError as exc:
        raise _error(404, "job not found", "not_found") from exc


@router.get("/jobs/{job_id}/screenshots")
def list_screenshots(job_id: str) -> List[Dict[str, Any]]:
    ledger = get_ledger()
    if ledger.get_job(job_id) is None:
        raise _error(404, "job not found", "not_found")
    from screenshots import public_screenshot_rows

    return public_screenshot_rows(ledger.list_screenshots(job_id))


@router.get("/jobs/{job_id}/screenshots/{shot_id}", response_model=None)
def get_screenshot_bytes(job_id: str, shot_id: str) -> Union[FileResponse, Response]:
    ledger = get_ledger()
    meta = ledger.get_screenshot(job_id, shot_id)
    if meta is None:
        raise _error(404, "screenshot not found", "not_found")
    ref = str(meta.get("storage_path") or "")
    from object_storage import (
        ObjectStorageError,
        is_s3_ref,
        make_s3_ref,
        object_key,
        object_storage_config,
        read_bytes,
        resolve_storage_backend,
    )

    # Prefer hot local cache; fall back to object storage (D72).
    if ref and not is_s3_ref(ref):
        path = Path(ref)
        if path.is_file():
            return FileResponse(path, media_type="image/png", filename=f"{shot_id}.png")

    fetch_ref = ref if is_s3_ref(ref) else ""
    if not fetch_ref and resolve_storage_backend() == "s3":
        conf = object_storage_config()
        if conf.bucket:
            key = object_key(
                kind="screenshot",
                job_id=job_id,
                filename=f"{shot_id}.png",
                prefix=conf.prefix,
            )
            fetch_ref = make_s3_ref(conf.bucket, key)

    if fetch_ref:
        try:
            data = read_bytes(fetch_ref)
        except ObjectStorageError as exc:
            raise _error(503, str(exc), "object_storage_misconfigured") from exc
        except FileNotFoundError as exc:
            raise _error(404, "screenshot file missing", "not_found") from exc
        except Exception as exc:  # noqa: BLE001
            raise _error(
                502,
                "screenshot object fetch failed",
                "object_storage_error",
            ) from exc
        return Response(
            content=data,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="{shot_id}.png"'},
        )
    raise _error(404, "screenshot file missing", "not_found")


def _sse_format(event_id: str, event_type: str, data: Dict[str, Any]) -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"


async def _event_stream(
    ledger: Ledger,
    job_id: str,
    *,
    after: Optional[str],
    keepalive_seconds: int,
) -> AsyncIterator[str]:
    cursor = after or None
    terminal = frozenset({"completed", "failed", "cancelled"})
    heartbeat_interval = max(1, keepalive_seconds)
    heartbeat_due = monotonic() + heartbeat_interval
    settings = get_settings()
    last_console = None

    while True:
        # Read the status before the events so a terminal transition during the
        # query cannot close the stream before its committed status event is sent.
        job = ledger.get_job(job_id)
        if job is None:
            yield _sse_format(
                cursor or "0",
                "error",
                {"message": "job disappeared", "code": "not_found"},
            )
            return

        events = ledger.list_events(job_id, after_event_id=cursor)
        for event in events:
            body = {
                "event_id": event.event_id,
                "type": event.type,
                "message": event.message,
                "payload": event.payload,
                "timestamp": event.timestamp,
            }
            if event.type == "status" and "status" in event.payload:
                body["status"] = event.payload["status"]
            # Replay and live delivery use the same shape expected by the browser.
            if event.type == "progress":
                for key in ("progress", "current_step"):
                    if key in event.payload:
                        body[key] = event.payload[key]
            yield _sse_format(event.event_id, event.type, body)
            cursor = event.event_id

        # Availability belongs to the current socket, so derive it on connection
        # and on change. Omitting the SSE id preserves the durable replay cursor.
        console = console_metadata(settings, ledger, job_id)
        if console is not None and console != last_console:
            payload = json.dumps({"payload": console}, separators=(",", ":"))
            yield f"event: novnc\ndata: {payload}\n\n"
            last_console = console

        if job.status in terminal:
            return

        if events:
            heartbeat_due = monotonic() + heartbeat_interval
        elif monotonic() >= heartbeat_due:
            yield ": keepalive\n\n"
            heartbeat_due = monotonic() + heartbeat_interval
        # Poll the durable ledger even between keep-alives to pick up other writers.
        await asyncio.sleep(min(1.0, max(0.0, heartbeat_due - monotonic())))


@router.get("/jobs/{job_id}/events/recent")
def job_events_recent(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> Dict[str, Any]:
    """Last N durable events ascending (D81 operator MCP ``tail_events``)."""
    ledger = get_ledger()
    if ledger.get_job(job_id) is None:
        raise _error(404, "job not found", "not_found")
    events = ledger.list_events_recent(job_id, limit=limit)
    return {
        "job_id": job_id,
        "limit": limit,
        "events": [
            {
                "event_id": ev.event_id,
                "type": ev.type,
                "message": ev.message,
                "payload": ev.payload,
                "timestamp": ev.timestamp,
            }
            for ev in events
        ],
    }


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    after: Optional[str] = Query(default=None),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
) -> Response:
    ledger = get_ledger()
    if ledger.get_job(job_id) is None:
        raise _error(404, "job not found", "not_found")

    cursor = after if after is not None else last_event_id
    if not ledger.cursor_is_valid(job_id, cursor):
        return JSONResponse(
            status_code=status.HTTP_410_GONE,
            content={
                "error": "SSE cursor expired or unknown; re-snapshot and resubscribe",
                "code": "cursor_expired",
            },
        )

    settings = get_settings()
    return StreamingResponse(
        _event_stream(
            ledger,  # Continue from the same ledger that validated the cursor.
            job_id,
            after=cursor,
            keepalive_seconds=settings.sse_keepalive_seconds,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/mcp")
async def operator_mcp_rpc(request: Request) -> Response:
    """Operator Killhub MCP JSON-RPC (D81). Tools call public Jobs API via env base URL."""
    from operator_mcp_tools import client_from_env, handle_jsonrpc

    try:
        request_body = await request.json()
    except Exception as exc:  # noqa: BLE001 — invalid JSON
        raise _error(400, "invalid JSON body", "invalid_rpc") from exc
    if not isinstance(request_body, dict):
        raise _error(400, "JSON-RPC body must be an object", "invalid_rpc")

    client = client_from_env()
    try:
        # HTTP tools call back through the frontend into this same sidecar.
        response = await asyncio.to_thread(handle_jsonrpc, client, request_body)
    finally:
        client.close()

    if response is None:
        return Response(status_code=204)
    return JSONResponse(content=response)


@router.get("/mcp")
def operator_mcp_info() -> Dict[str, Any]:
    """Discoverability for the operator MCP HTTP endpoint (D81)."""
    return {
        "name": "killhub",
        "transport": "json-rpc",
        "protocolVersion": "2024-11-05",
        "path": "/internal/mcp",
        "methods": [
            "initialize",
            "tools/list",
            "tools/call",
            "resources/list",
            "resources/templates/list",
            "resources/read",
        ],
    }
