"""Background worker — claims pending jobs; optional bootstrap → finalize."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from config import Settings, get_settings
from service import claim_pending_job

if TYPE_CHECKING:
    from ledger import Ledger

logger = logging.getLogger("killhub.worker")


async def worker_loop(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    poll = max(cfg.worker_poll_seconds, 0.2)
    logger.info(
        "worker started (poll=%ss auto_create=%s discover=%s install=%s verify=%s "
        "screenshots=%s containment=%s finalize=%s)",
        poll,
        cfg.msb_auto_create,
        cfg.discover_on_claim,
        cfg.install_on_claim,
        cfg.verify_on_claim,
        cfg.screenshots_on_claim,
        cfg.containment_on_claim,
        cfg.finalize_on_claim,
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
                    or cfg.finalize_on_claim
                ):
                    await asyncio.to_thread(_run_claimed_job, claimed.job_id, cfg)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — keep loop alive
            logger.exception("worker iteration failed")
        await asyncio.sleep(poll)


def _run_claimed_job(job_id: str, settings: Settings) -> None:
    from profile import ProfileError

    from containment import ContainmentError
    from discover import DiscoverError
    from errors import HarnessError
    from finalize import FinalizeError
    from install import InstallError
    from jobs import get_ledger
    from selfheal import heal_lost_sandbox
    from verify import VerifyError

    ledger = get_ledger(settings)
    pipeline = (
        settings.discover_on_claim
        or settings.install_on_claim
        or settings.verify_on_claim
        or settings.screenshots_on_claim
        or settings.containment_on_claim
        or settings.finalize_on_claim
    )
    heals = 0
    max_heals = max(int(settings.max_sandbox_heals or 0), 0)
    while True:
        try:
            _run_pipeline_once(job_id, settings, pipeline=pipeline)
            return
        except (
            HarnessError,
            DiscoverError,
            ProfileError,
            InstallError,
            VerifyError,
            ContainmentError,
            FinalizeError,
        ) as exc:
            # D80: a vanished sandbox is re-provisioned, not retried against.
            if (
                pipeline
                and heals < max_heals
                and heal_lost_sandbox(
                    job_id,
                    cause=getattr(exc, "message", str(exc)),
                    attempt=heals + 1,
                    settings=settings,
                )
            ):
                heals += 1
                continue
            _fail_claimed_job(job_id, exc, ledger=ledger, settings=settings)
            return


def _run_pipeline_once(job_id: str, settings: Settings, *, pipeline: bool) -> None:
    from containment import run_containment_probes
    from discover import discover_runtime_profile
    from finalize import finalize_job
    from harness import (
        create_environment,
        default_bootstrap_plan,
        wait_until_ready,
    )
    from install import provision_and_go_offline
    from jobs import get_ledger
    from screenshots import maybe_capture_after_verify
    from verify import verify_readiness

    ledger = get_ledger(settings)
    if pipeline:
        discover_runtime_profile(job_id, settings=settings, create=True)
        if (
            settings.install_on_claim
            or settings.verify_on_claim
            or settings.screenshots_on_claim
            or settings.containment_on_claim
            or settings.finalize_on_claim
        ):
            provision_and_go_offline(job_id, settings=settings)
        if (
            settings.verify_on_claim
            or settings.screenshots_on_claim
            or settings.containment_on_claim
            or settings.finalize_on_claim
        ):
            verify_readiness(job_id, settings=settings)
        if settings.screenshots_on_claim or settings.finalize_on_claim:
            maybe_capture_after_verify(job_id, settings=settings)
        if settings.containment_on_claim or settings.finalize_on_claim:
            run_containment_probes(job_id, settings=settings)
        if settings.finalize_on_claim:
            finalize_job(job_id, settings=settings)
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


def _fail_claimed_job(job_id: str, exc: Exception, *, ledger: Ledger, settings: Settings) -> None:
    from finalize import finalize_job

    message = getattr(exc, "message", str(exc))
    code = getattr(exc, "code", "worker_error")
    logger.error("claimed job %s failed: %s", job_id, message)
    job = ledger.get_job(job_id)
    # A cancel-frozen job is finalized by the cancel path, not here (D61).
    # setup_failed fixtures may already have verification while still
    # non-terminal; reclaim via finalize when enabled (D37, D53).
    if (
        job is not None
        and job.status not in {"failed", "cancelled", "completed"}
        and job.cancel_requested_at is None
    ):
        ledger.append_event(
            job_id,
            typ="error",
            message=message,
            payload={"code": code, "phase": "worker_pipeline"},
        )
        ledger.update_job_fields(
            job_id,
            error=message,
            current_step="pipeline failed",
        )
        if settings.finalize_on_claim:
            # Best-effort SCA + receipt + destroy on fail paths (D53, D37).
            try:
                finalize_job(job_id, settings=settings)
                return
            except Exception:  # noqa: BLE001
                logger.exception("finalize after failure also failed for %s", job_id)
        # Fallback: receipt + terminal status event + status atomically (D61).
        ledger.finalize_job(
            job_id,
            status="failed",
            # Preserve failure evidence after upstream sandbox recovery is exhausted.
            include_verdict=True,
            receipt={
                "verification": job.verification
                or {"kind": "setup_failed", "original_failure": {"summary": message}},
                "dossier": {"outcome": "failed", "code": code, "phase": "worker_pipeline"},
            },
            event_payload={"reason": code},
            current_step="pipeline failed",
            error=message,
            progress=100,
        )
        try:
            from service import release_admission_slot

            release_admission_slot(was_running=True, settings=settings)
        except Exception:  # noqa: BLE001
            logger.exception("admission release failed for %s", job_id)
