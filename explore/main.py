"""Killhub explore sidecar — Plane 1 worker entry (D28, D52)."""

from __future__ import annotations

import asyncio
import fcntl
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import FastAPI, Response

from api.routes import router as internal_router
from config import get_settings
from harness import HarnessError, MsbCli
from jobs import init_ledger, reset_ledger_for_tests
from novnc_bridge import router as novnc_router
from reaper import reaper_loop, recover_interrupted_jobs
from worker import worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("killhub.explore")


@contextmanager
def _worker_group(db_path: Path | None):
    """Only the first SQLite worker after downtime may reconcile interrupted work."""
    if db_path is None:
        yield False
        return
    with db_path.with_name(db_path.name + ".workers.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fcntl.flock(lock, fcntl.LOCK_SH)
            yield False
        else:
            yield lock


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    ledger = init_ledger(settings)
    with _worker_group(ledger.db_path) as first_worker:
        try:
            if first_worker:
                await asyncio.to_thread(recover_interrupted_jobs, settings, MsbCli(settings))
        except (HarnessError, ValueError) as exc:
            logger.warning("Restart recovery deferred: %s", exc)
        if first_worker:
            fcntl.flock(first_worker, fcntl.LOCK_SH)
        worker_task = asyncio.create_task(worker_loop(settings), name="killhub-worker")
        reaper_task = asyncio.create_task(reaper_loop(settings), name="killhub-reaper")
        logger.info(
            "explore listening intent host=%s port=%s",
            settings.explore_host,
            settings.explore_port,
        )
        try:
            yield
        finally:
            for task in (worker_task, reaper_task):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            reset_ledger_for_tests()


app = FastAPI(title="Killhub explore", version="0.0.4", lifespan=lifespan)
app.include_router(internal_router)
# This ASGI route owns the upgrade. The edge must expose only the public console path.
app.include_router(novnc_router)


@app.middleware("http")
async def operator_mcp_http_compat(request, call_next):  # type: ignore[no-untyped-def]
    """Streamable HTTP–friendly statuses for /internal/mcp without rewriting routes (D81)."""
    path = request.url.path.rstrip("/") or "/"
    if path == "/internal/mcp" and request.method == "GET":
        return Response(status_code=405, headers={"Allow": "POST"})
    if path == "/internal/mcp" and request.method == "POST":
        from operator_mcp_tools import mcp_http_mode

        token = mcp_http_mode.set(True)
        try:
            response = await call_next(request)
        finally:
            mcp_http_mode.reset(token)
        # Notifications used to return 204; Streamable HTTP wants 202 Accepted.
        if response.status_code == 204:
            return Response(status_code=202)
        return response
    return await call_next(request)


@app.get("/internal/health")
def internal_health(response: Response) -> dict[str, object]:
    """Sidecar + ledger liveness (unauthenticated for compose probes)."""
    settings = get_settings()
    try:
        from jobs import get_ledger

        ledger = get_ledger(settings)
        job_count = ledger.count_jobs()
        ledger_status: dict[str, object] = {
            "ok": True,
            "engine": ledger.engine,
            "path": str(ledger.db_path) if ledger.db_path else None,
            "job_count": job_count,
        }
        ok = True
    except Exception as exc:  # noqa: BLE001 — health must not raise
        ledger_status = {"ok": False, "error": str(exc)}
        ok = False

    admission_status: dict[str, object]
    try:
        from admission import get_admission_store

        store = get_admission_store()
        store.ping()
        admission_status = {
            "ok": True,
            "backend": store.backend,
            "gauges": store.gauges(),
        }
    except Exception as exc:  # noqa: BLE001 — health must not raise
        admission_status = {"ok": False, "error": str(exc)}
        ok = False

    response.status_code = 200 if ok else 503
    return {
        "ok": ok,
        "service": "explore",
        "ledger": ledger_status,
        "admission": admission_status,
        "port": settings.explore_port,
    }


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.explore_host,
        port=settings.explore_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
