"""Fail non-terminal jobs that timed out, stalled, or passed expires_at (D81).

Plane-1 reaper calls :func:`reap_stale_jobs` after absolute sandbox expiry so
the ledger never leaves a run looking "live" with a dead or absent worker.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import Settings, get_settings
from harness import MsbCli
from jobs import get_ledger
from ledger import Ledger
from ledger.store import TERMINAL_STATUSES, utc_now
from models import CleanupState, Job

logger = logging.getLogger("killhub.stall")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(iso: str | None, *, now: datetime) -> float | None:
    then = _parse_iso(iso)
    if then is None:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds())


def fail_job(
    job_id: str,
    *,
    code: str,
    reason: str,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    destroy: bool = True,
    observed: Job | None = None,
) -> dict[str, Any]:
    """Destroy any live sandbox (best effort) and finalize the job as failed."""
    from harness import destroy_environment
    from service import release_admission_slot

    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None or job.status in TERMINAL_STATUSES or (observed is not None and job != observed):
        # A heartbeat after the reaper's scan invalidates the stale observation.
        return {"job_id": job_id, "reason": code, "finalized": False}

    # The absolute-expiry reaper may already have confirmed this generation.
    confirmed = bool(job.sandbox_id and job.destroyed_at)
    was_running = job.status not in {"pending", "queued"}
    destroy_error: str | None = None
    attempts = job.cleanup.attempts
    if destroy and job.sandbox_id and not confirmed:
        msb = cli or MsbCli(cfg)
        attempts = attempts + 1
        now_cleanup = utc_now()
        try:
            ledger.update_job_fields(
                job_id,
                finalizer=True,
                cleanup=CleanupState(
                    status="destroying",
                    attempts=attempts,
                    updated_at=now_cleanup,
                ),
            )
        except Exception:  # noqa: BLE001
            logger.exception("cleanup mark failed for %s", job_id)
        result = destroy_environment(
            job.sandbox_id,
            job_id=job_id,
            reason=code,
            settings=cfg,
            cli=msb,
            finalizer=True,
        )
        confirmed = bool(result.confirmed)
        destroy_error = result.error
        current = ledger.get_job(job_id)
        if (
            current is None
            or current.status in TERMINAL_STATUSES
            or current.current_sandbox_generation != job.current_sandbox_generation
        ):
            return {"job_id": job_id, "reason": code, "finalized": False}
        job = current

    now = utc_now()
    status = "cancelled" if job.cancel_requested_at else "failed"
    verification = job.verification or {
        "kind": "setup_failed",
        "original_failure": {"step": code, "summary": reason},
    }
    fields: dict[str, Any] = {
        "current_step": status,
        "error": reason,
        "progress": 100,
    }
    if confirmed:
        fields["destroyed_at"] = job.destroyed_at or now
        fields["cleanup"] = CleanupState(
            status="destroyed",
            attempts=attempts,
            updated_at=now,
        )
    elif destroy and job.sandbox_id:
        fields["cleanup"] = CleanupState(
            status="destroy_failed",
            attempts=attempts,
            last_error=destroy_error,
            updated_at=now,
        )

    lifecycle: dict[str, Any] | None = None
    if confirmed and job.sandbox_id:
        lifecycle = {
            "confirmed": True,
            "cleanup": "destroyed",
            "environment_id": job.sandbox_id,
            "generation": job.current_sandbox_generation,
            "destroyed_at": fields.get("destroyed_at", now),
            "reason": code,
            "phase": "destroyed",
        }

    prior_receipt = ledger.get_receipt(job_id) or {}
    receipt: dict[str, Any] = {
        "verification": verification,
        "dossier": {
            **(prior_receipt.get("dossier") or {}),
            "outcome": status,
            "code": code,
            "interrupted_step": job.current_step,
        },
    }
    if destroy and job.sandbox_id and not confirmed:
        lifecycle = {
            "confirmed": False,
            "cleanup": "destroy_failed",
            "destroy_error": destroy_error,
            "reason": code,
        }
    if lifecycle is not None:
        receipt["lifecycle"] = lifecycle

    try:
        ledger.finalize_job(
            job_id,
            status=status,  # type: ignore[arg-type]
            include_verdict=True,
            expected_job=job,
            receipt=receipt,
            event_message=reason,
            event_payload={"reason": code},
            **fields,
        )
    except Ledger.WriterFrozenError:
        return {"job_id": job_id, "reason": code, "finalized": False}
    except Exception:  # noqa: BLE001
        logger.exception("finalize failed for stalled job %s", job_id)
        return {
            "job_id": job_id,
            "reason": code,
            "finalized": False,
            "error": "finalize_failed",
        }

    try:
        release_admission_slot(was_running=was_running, settings=cfg)
    except Exception:  # noqa: BLE001
        logger.exception("admission release failed for %s", job_id)

    return {
        "job_id": job_id,
        "reason": code,
        "finalized": True,
        "confirmed_destroy": confirmed,
        "error": destroy_error,
    }


def classify_stale_job(
    job: Any,
    *,
    now: datetime,
    settings: Settings,
) -> str | None:
    """Return dossier code if the non-terminal job should be failed, else None."""
    if job.status in TERMINAL_STATUSES:
        return None

    created_age = _age_seconds(job.created_at, now=now)
    updated_age = _age_seconds(job.updated_at, now=now)
    expires = _parse_iso(job.expires_at)
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    waiting = job.status in {"pending", "queued"}

    job_timeout = max(int(settings.job_timeout_seconds or 0), 0)
    stall_timeout = max(int(settings.job_stall_seconds or 0), 0)

    # Absolute wall clock from create (documented JOB_TIMEOUT_SECONDS).
    if job_timeout and created_age is not None and created_age >= job_timeout:
        return "job_timeout"

    # Absolute sandbox/job expiry — including runs that never created a VM.
    if expires is not None and expires <= now:
        return "expires_at"

    # Silence on ledger updates (heartbeats keep updated_at fresh).
    if stall_timeout and not waiting and updated_age is not None and updated_age >= stall_timeout:
        return "job_stalled"

    return None


def reap_stale_jobs(
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Scan non-terminal jobs and fail those past timeout / stall / expires_at."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    now = now or datetime.now(timezone.utc)
    msb = cli or MsbCli(cfg)
    actions: list[dict[str, Any]] = []

    for job in ledger.list_jobs():
        code = classify_stale_job(job, now=now, settings=cfg)
        if code is None:
            continue
        reason = {
            "job_timeout": (
                f"Job exceeded JOB_TIMEOUT_SECONDS ({cfg.job_timeout_seconds}s) "
                f"without reaching a terminal status."
            ),
            "expires_at": (
                f"Job passed absolute expires_at ({job.expires_at}) "
                "without reaching a terminal status."
            ),
            "job_stalled": (
                f"No ledger activity for JOB_STALL_SECONDS ({cfg.job_stall_seconds}s); "
                "worker appears stalled."
            ),
        }.get(code, f"Job closed by reaper ({code}).")
        logger.info(
            "reaping stale job=%s code=%s status=%s step=%s",
            job.job_id,
            code,
            job.status,
            job.current_step,
        )
        actions.append(
            fail_job(
                job.job_id,
                code=code,
                reason=reason,
                settings=cfg,
                cli=msb,
                destroy=bool(job.sandbox_id),
                observed=job,
            )
        )
    return actions


def reason_for_misconfigured_worker() -> str:
    return (
        "Worker claimed the job but no pipeline flags are enabled "
        "(MSB_AUTO_CREATE / DISCOVER_ON_CLAIM / INSTALL_ON_CLAIM / "
        "VERIFY_ON_CLAIM / SCREENSHOTS_ON_CLAIM / CONTAINMENT_ON_CLAIM / "
        "FINALIZE_ON_CLAIM)."
    )


__all__ = [
    "classify_stale_job",
    "fail_job",
    "reap_stale_jobs",
    "reason_for_misconfigured_worker",
]
