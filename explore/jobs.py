"""Job helpers over the durable ledger (D41, D52, D73)."""

from __future__ import annotations

from typing import Any

from config import Settings, get_settings
from ledger import Ledger
from models import EventType, Job, JobEvent, ProfilePhase, ReconcileReport, SandboxState

_ledger: Ledger | None = None


def get_ledger(settings: Settings | None = None) -> Ledger:
    global _ledger
    if _ledger is None:
        cfg = settings or get_settings()
        _ledger = Ledger.from_url(
            cfg.ledger_url,
            max_job_log_bytes=cfg.max_job_log_bytes,
        )
    return _ledger


def reset_ledger_for_tests() -> None:
    """Close and drop the process-wide ledger handle (tests only)."""
    global _ledger
    if _ledger is not None:
        _ledger.close()
        _ledger = None


def init_ledger(settings: Settings | None = None) -> Ledger:
    """Open ledger + run startup reconciliation (msb inventory optional)."""
    ledger = get_ledger(settings)
    ledger.reconcile_startup(live_environment_ids=None)
    return ledger


def create_job(git_url: str, *, settings: Settings | None = None) -> Job:
    from service import create_job as _create

    return _create(git_url, settings=settings)


def append_event(
    job_id: str,
    *,
    typ: EventType,
    message: str,
    payload: dict[str, Any] | None = None,
    finalizer: bool = False,
) -> JobEvent:
    return get_ledger().append_event(
        job_id,
        typ=typ,
        message=message,
        payload=payload,
        finalizer=finalizer,
    )


def get_snapshot(job_id: str) -> dict[str, Any] | None:
    return get_ledger().get_snapshot(job_id)


def append_profile_revision(
    job_id: str,
    *,
    phase: ProfilePhase,
    schema_version: str,
    profile: dict[str, Any],
    storage_path: str | None = None,
) -> Any:
    return get_ledger().append_profile_revision(
        job_id,
        phase=phase,
        schema_version=schema_version,
        profile=profile,
        storage_path=storage_path,
    )


def append_sandbox_generation(
    job_id: str,
    *,
    environment_id: str,
    image: str,
    state: SandboxState = "provisioning",
    cpus: float | None = None,
    memory: str | None = None,
) -> Any:
    ledger = get_ledger()
    job = ledger.get_job(job_id)
    if job is None:
        raise KeyError(f"unknown job_id: {job_id}")
    return ledger.append_sandbox_generation(
        job_id,
        environment_id=environment_id,
        image=image,
        expires_at=job.expires_at,
        state=state,
        cpus=cpus,
        memory=memory,
    )


def reconcile() -> ReconcileReport:
    return get_ledger().reconcile_startup(live_environment_ids=None)
