"""Killhub explore sidecar — Plane 1 worker entry (D28, D52)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import router as internal_router
from config import get_settings
from jobs import init_ledger, reset_ledger_for_tests
from worker import worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("killhub.explore")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    init_ledger(settings)
    task = asyncio.create_task(worker_loop(settings), name="killhub-worker-stub")
    logger.info(
        "explore listening intent host=%s port=%s",
        settings.explore_host,
        settings.explore_port,
    )
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        reset_ledger_for_tests()


app = FastAPI(title="Killhub explore", version="0.0.3", lifespan=lifespan)
app.include_router(internal_router)


@app.get("/internal/health")
def internal_health() -> dict[str, object]:
    """Sidecar + ledger liveness (unauthenticated for compose probes)."""
    settings = get_settings()
    try:
        from jobs import get_ledger

        ledger = get_ledger(settings)
        job_count = len(ledger.list_jobs())
        ledger_status: dict[str, object] = {
            "ok": True,
            "engine": "sqlite",
            "path": str(ledger.db_path),
            "job_count": job_count,
        }
        ok = True
    except Exception as exc:  # noqa: BLE001 — health must not raise
        ledger_status = {"ok": False, "error": str(exc)}
        ok = False

    return {
        "ok": ok,
        "service": "explore",
        "ledger": ledger_status,
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
