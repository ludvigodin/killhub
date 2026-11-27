"""Self-healing for a lost Plane-2 sandbox (D80).

A job's microVM can vanish mid-pipeline (host-side removal, crash, a reaper
race). Retrying install/verify against a VM that no longer exists only burns
repair attempts and ends in a misleading failure. Instead the worker:

1. confirms the sandbox is really gone (``msb status`` → not found, or it is
   stuck shutting down),
2. records a ``lifecycle`` event and marks that generation ``failed``,
3. force-removes any remnant, clears ``sandbox_id`` so discover bootstraps a
   fresh generation, and re-runs the pipeline,

bounded by ``MAX_SANDBOX_HEALS``. Still one live VM per job (D27); the job's
absolute ``expires_at`` is inherited, never extended (D41). Heals never invent
success — readiness still comes only from the verify gates (D47).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from config import Settings, get_settings
from errors import HarnessError
from harness import MsbCli, stop_and_remove_sandbox
from ledger.store import utc_now

logger = logging.getLogger("killhub.selfheal")

_GONE_MARKERS = ("not found", "no such sandbox")
_DYING_MARKERS = ("shutdown is already in progress",)
_TERMINAL = {"failed", "cancelled", "completed"}


def sandbox_alive(environment_id: str, *, cli: MsbCli) -> bool | None:
    """True = running/known, False = gone or shutting down, None = unknown."""
    try:
        result = cli.status(environment_id)
    except HarnessError:
        return None  # msb itself unavailable: never call that a lost VM
    text = f"{result.stdout}\n{result.stderr}".lower()
    if any(m in text for m in _GONE_MARKERS + _DYING_MARKERS):
        return False
    if result.ok:
        return True
    return None


def _expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) >= deadline


def heal_lost_sandbox(
    job_id: str,
    *,
    cause: str,
    attempt: int,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> bool:
    """Prepare a job to re-run after its sandbox was lost. True = retry now."""
    from jobs import get_ledger

    cfg = settings or get_settings()
    msb = cli or MsbCli(cfg)
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None or not job.sandbox_id:
        return False
    if job.status in _TERMINAL or job.cancel_requested_at is not None:
        return False
    if job.destroyed_at is not None or _expired(job.expires_at):
        return False
    env_id = job.sandbox_id
    dying = any(m in cause.lower() for m in _DYING_MARKERS)
    if not dying and sandbox_alive(env_id, cli=msb) is not False:
        return False  # VM still there (or unknown): a real failure, not a loss

    logger.warning("job %s lost sandbox %s; self-heal attempt %d", job_id, env_id, attempt)
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox lost",
        payload={
            "phase": "lost",
            "environment_id": env_id,
            "generation": job.current_sandbox_generation,
            "cause": cause[:300],
            "heal_attempt": attempt,
        },
    )
    # Never reuse the job's sandbox name while a prior VM may still own it.
    removal = stop_and_remove_sandbox(env_id, cli=msb, force_stop=True)
    if not removal.confirmed:
        logger.warning("sandbox recovery blocked for job %s: %s", job_id, removal.error)
        return False
    if job.current_sandbox_generation is not None:
        ledger.mark_generation_state(
            job_id, job.current_sandbox_generation, "failed", destroyed_at=utc_now()
        )
    ledger.update_job_fields(
        job_id,
        sandbox_id=None,
        status="repairing",
        current_step=f"self-heal: recreating sandbox (attempt {attempt})",
    )
    ledger.append_event(
        job_id,
        typ="log",
        message=f"self-heal attempt {attempt}: recreating sandbox and re-running pipeline",
        payload={"kind": "self_heal", "attempt": attempt, "lost_environment_id": env_id},
    )
    return True
