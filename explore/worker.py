"""Background worker stub — claims pending jobs; no sandbox yet (step 04)."""

from __future__ import annotations

import asyncio
import logging

from config import Settings, get_settings
from service import claim_pending_job

logger = logging.getLogger("killhub.worker")


async def worker_loop(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    poll = max(cfg.worker_poll_seconds, 0.2)
    logger.info("worker stub started (poll=%ss)", poll)
    while True:
        try:
            claimed = await asyncio.to_thread(claim_pending_job)
            if claimed is not None:
                logger.info("claimed job %s", claimed.job_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep loop alive
            logger.exception("worker stub iteration failed")
        await asyncio.sleep(poll)
