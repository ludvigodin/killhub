"""Background worker — claims pending jobs; optional T0 sandbox create."""

from __future__ import annotations

import asyncio
import logging

from config import Settings, get_settings
from service import claim_pending_job

logger = logging.getLogger("killhub.worker")


async def worker_loop(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    poll = max(cfg.worker_poll_seconds, 0.2)
    logger.info("worker started (poll=%ss auto_create=%s)", poll, cfg.msb_auto_create)
    while True:
        try:
            claimed = await asyncio.to_thread(claim_pending_job)
            if claimed is not None:
                logger.info("claimed job %s", claimed.job_id)
                if cfg.msb_auto_create:
                    await asyncio.to_thread(_bootstrap_sandbox, claimed.job_id, cfg)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep loop alive
            logger.exception("worker iteration failed")
        await asyncio.sleep(poll)


def _bootstrap_sandbox(job_id: str, settings: Settings) -> None:
    from harness import (
        HarnessError,
        create_environment,
        default_bootstrap_plan,
        wait_until_ready,
    )
    from jobs import get_ledger

    try:
        gen = create_environment(job_id, default_bootstrap_plan(settings), settings=settings)
        wait_until_ready(gen.environment_id, settings=settings)
        ledger = get_ledger(settings)
        ledger.update_job_fields(
            job_id,
            current_step="sandbox running (bootstrap)",
            progress=20,
            steps_completed=["pending", "provisioning"],
        )
    except HarnessError as exc:
        logger.error("bootstrap sandbox failed for %s: %s", job_id, exc.message)
        ledger = get_ledger(settings)
        ledger.update_job_fields(
            job_id,
            status="failed",
            current_step="sandbox create failed",
            error=exc.message,
            progress=100,
        )
        ledger.append_event(
            job_id,
            typ="error",
            message=exc.message,
            payload={"code": exc.code, "phase": "bootstrap"},
        )
