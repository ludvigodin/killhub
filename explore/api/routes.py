"""Internal Worker API routes (D52, D55, D61)."""

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from api.auth import require_internal_token
from config import get_settings
from jobs import get_ledger
from ledger.store import validate_github_url
from service import (
    AdmissionError,
    cancel_job,
    create_job,
    get_public_snapshot,
    list_job_summaries,
)

router = APIRouter(
    prefix="/internal",
    dependencies=[Depends(require_internal_token)],
)


class CreateJobBody(BaseModel):
    github_url: str = Field(min_length=1)


def _error(status_code: int, message: str, code: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": message, "code": code},
    )


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def post_job(body: CreateJobBody) -> Dict[str, str]:
    try:
        validate_github_url(body.github_url)
    except ValueError as exc:
        raise _error(400, str(exc), "invalid_url") from exc
    try:
        job = create_job(body.github_url)
    except AdmissionError as exc:
        raise _error(exc.status_code, exc.message, exc.code) from exc
    except ValueError as exc:
        raise _error(400, str(exc), "invalid_url") from exc
    return {"job_id": job.job_id}


@router.get("/jobs")
def list_jobs(
    limit: int = Query(default=48, ge=1, le=200),
) -> Dict[str, Any]:
    """Recent jobs newest-first for the public feed (D69)."""
    return {"jobs": list_job_summaries(limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> Dict[str, Any]:
    snap = get_public_snapshot(job_id)
    if snap is None:
        raise _error(404, "job not found", "not_found")
    return snap


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
    return ledger.list_screenshots(job_id)


@router.get("/jobs/{job_id}/screenshots/{shot_id}")
def get_screenshot_bytes(job_id: str, shot_id: str) -> FileResponse:
    ledger = get_ledger()
    meta = ledger.get_screenshot(job_id, shot_id)
    if meta is None:
        raise _error(404, "screenshot not found", "not_found")
    path = Path(meta["storage_path"])
    if not path.is_file():
        raise _error(404, "screenshot file missing", "not_found")
    return FileResponse(path, media_type="image/png", filename=f"{shot_id}.png")


def _sse_format(event_id: str, event_type: str, data: Dict[str, Any]) -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload}\n\n"


async def _event_stream(
    job_id: str,
    *,
    after: Optional[str],
    keepalive_seconds: int,
) -> AsyncIterator[str]:
    ledger = get_ledger()
    cursor = after
    terminal = frozenset({"completed", "failed", "cancelled"})

    for event in ledger.list_events(job_id, after_event_id=cursor):
        body: Dict[str, Any] = {
            "event_id": event.event_id,
            "type": event.type,
            "message": event.message,
            "payload": event.payload,
            "timestamp": event.timestamp,
        }
        if event.type == "status" and "status" in event.payload:
            body["status"] = event.payload["status"]
        if event.type == "progress":
            for key in ("progress", "current_step"):
                if key in event.payload:
                    body[key] = event.payload[key]
        yield _sse_format(event.event_id, event.type, body)
        cursor = event.event_id

    job = ledger.get_job(job_id)
    if job is not None and job.status in terminal:
        return

    while True:
        await asyncio.sleep(min(keepalive_seconds, 2))
        job = ledger.get_job(job_id)
        if job is None:
            yield _sse_format(
                cursor or "0",
                "error",
                {"message": "job disappeared", "code": "not_found"},
            )
            return

        new_events = ledger.list_events(job_id, after_event_id=cursor)
        if not new_events:
            yield ": keepalive\n\n"
            if job.status in terminal:
                return
            await asyncio.sleep(max(keepalive_seconds - 2, 0))
            continue

        for event in new_events:
            body = {
                "event_id": event.event_id,
                "type": event.type,
                "message": event.message,
                "payload": event.payload,
                "timestamp": event.timestamp,
            }
            if event.type == "status" and "status" in event.payload:
                body["status"] = event.payload["status"]
            yield _sse_format(event.event_id, event.type, body)
            cursor = event.event_id

        job = ledger.get_job(job_id)
        if job is not None and job.status in terminal:
            return


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
