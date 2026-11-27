"""Background worker — claims pending jobs; optional bootstrap → containment."""

from __future__ import annotations

import asyncio
import logging

from config import Settings, get_settings
from service import claim_pending_job

logger = logging.getLogger("killhub.worker")


async def worker_loop(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    poll = max(cfg.worker_poll_seconds, 0.2)
    logger.info(
        "worker started (poll=%ss auto_create=%s discover=%s install=%s verify=%s "
        "screenshots=%s containment=%s)",
        poll,
        cfg.msb_auto_create,
        cfg.discover_on_claim,
        cfg.install_on_claim,
        cfg.verify_on_claim,
        cfg.screenshots_on_claim,
        cfg.containment_on_claim,
    )
    while True:
        try:
            claimed = await asyncio.to_thread(claim_pending_job)
            if claimed is not None:
                logger.info("claimed job %s", claimed.job_id)
                if (
                    cfg.msb_auto_create
                    or cfg.discover_on_claim
                    or cfg.install_on_claim
                    or cfg.verify_on_claim
                    or cfg.screenshots_on_claim
                    or cfg.containment_on_claim
                ):
                    await asyncio.to_thread(_run_claimed_job, claimed.job_id, cfg)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep loop alive
            logger.exception("worker iteration failed")
        await asyncio.sleep(poll)


def _run_claimed_job(job_id: str, settings: Settings) -> None:
    from profile import ProfileError

    from containment import ContainmentError, run_containment_probes
    from discover import DiscoverError, discover_runtime_profile
    from errors import HarnessError
    from harness import (
        create_environment,
        default_bootstrap_plan,
        wait_until_ready,
    )
    from install import InstallError, provision_and_go_offline
    from jobs import get_ledger
    from screenshots import maybe_capture_after_verify
    from verify import VerifyError, verify_readiness

    ledger = get_ledger(settings)
    try:
        if (
            settings.discover_on_claim
            or settings.install_on_claim
            or settings.verify_on_claim
            or settings.screenshots_on_claim
            or settings.containment_on_claim
        ):
            discover_runtime_profile(job_id, settings=settings, create=True)
            if (
                settings.install_on_claim
                or settings.verify_on_claim
                or settings.screenshots_on_claim
                or settings.containment_on_claim
            ):
                provision_and_go_offline(job_id, settings=settings)
            if (
                settings.verify_on_claim
                or settings.screenshots_on_claim
                or settings.containment_on_claim
            ):
                verify_readiness(job_id, settings=settings)
            if settings.screenshots_on_claim:
                maybe_capture_after_verify(job_id, settings=settings)
            if settings.containment_on_claim:
                run_containment_probes(job_id, settings=settings)
            return
        # Legacy T0 path: bootstrap create only.
        gen = create_environment(job_id, default_bootstrap_plan(settings), settings=settings)
        wait_until_ready(gen.environment_id, settings=settings)
        ledger.update_job_fields(
            job_id,
            current_step="sandbox running (bootstrap)",
            progress=20,
            steps_completed=["pending", "provisioning"],
        )
    except (
        HarnessError,
        DiscoverError,
        ProfileError,
        InstallError,
        VerifyError,
        ContainmentError,
    ) as exc:
        message = getattr(exc, "message", str(exc))
        code = getattr(exc, "code", "worker_error")
        logger.error("claimed job %s failed: %s", job_id, message)
        job = ledger.get_job(job_id)
        if job is not None and job.status not in {"failed", "cancelled", "completed"}:
            ledger.update_job_fields(
                job_id,
                status="failed",
                current_step="pipeline failed",
                error=message,
                progress=100,
            )
            ledger.append_event(
                job_id,
                typ="error",
                message=message,
                payload={"code": code, "phase": "worker_pipeline"},
            )
