"""Job-facing services over the ledger (create / cancel / snapshot) — D52 / D61."""

from __future__ import annotations

from typing import Any

from config import Settings, get_settings
from jobs import get_ledger
from ledger import Ledger
from ledger.store import utc_now
from models import CleanupState, Job

TERMINAL = frozenset({"completed", "failed", "cancelled"})
QUEUED_STATUSES = frozenset({"pending", "queued"})
RUNNING_STATUSES = frozenset(
    {
        "analyzing",
        "planning",
        "provisioning",
        "installing",
        "verifying",
        "repairing",
        "scanning",
        "finalizing",
    }
)


class AdmissionError(Exception):
    def __init__(self, message: str, code: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _enforce_admission(cfg: Settings) -> None:
    """Reject create when concurrency + queue capacity is exhausted (D40)."""
    if cfg.inference_budget_reject:
        raise AdmissionError(
            "Inference budget exhausted",
            code="inference_budget",
            status_code=429,
        )
    ledger = get_ledger(cfg)
    jobs = ledger.list_jobs()
    running = sum(1 for j in jobs if j.status in RUNNING_STATUSES)
    queued = sum(1 for j in jobs if j.status in QUEUED_STATUSES)
    capacity = cfg.max_concurrent_jobs + cfg.max_queued_jobs
    active = running + queued
    if active >= capacity:
        raise AdmissionError(
            "Job concurrency and queue are full",
            code="queue_full",
            status_code=503,
        )
    if running >= cfg.max_concurrent_jobs and queued >= cfg.max_queued_jobs:
        raise AdmissionError(
            "Job concurrency and queue are full",
            code="queue_full",
            status_code=503,
        )


def create_job(github_url: str, *, settings: Settings | None = None) -> Job:
    cfg = settings or get_settings()
    _enforce_admission(cfg)
    return get_ledger(cfg).create_job(github_url, env_ttl_seconds=cfg.env_ttl_seconds)


def get_public_snapshot(job_id: str) -> dict[str, Any] | None:
    return get_ledger().get_snapshot(job_id)


def cancel_job(job_id: str) -> dict[str, Any]:
    """
    D61 cancel: request → freeze → finalizer (receipt + cleanup stub) → terminal cancelled.

    No Microsandbox yet — cleanup is confirmed immediately when no live generation
    needs destroy, or marked destroyed without msb when a generation row exists.
    """
    ledger = get_ledger()
    job = ledger.get_job(job_id)
    if job is None:
        raise KeyError(f"unknown job_id: {job_id}")

    if job.status in TERMINAL:
        snap = ledger.get_snapshot(job_id)
        assert snap is not None
        return snap

    now = utc_now()
    if job.cancel_requested_at is None:
        ledger.update_job_fields(
            job_id,
            finalizer=True,
            cancel_requested_at=now,
            current_step="cancel requested",
        )
        ledger.append_event(
            job_id,
            typ="log",
            message="cancel requested",
            payload={"kind": "cancel"},
            finalizer=True,
        )

    job = ledger.get_job(job_id)
    assert job is not None
    if job.status in TERMINAL:
        snap = ledger.get_snapshot(job_id)
        assert snap is not None
        return snap

    _run_cancel_finalizer(ledger, job_id)
    snap = ledger.get_snapshot(job_id)
    assert snap is not None
    return snap


def _run_cancel_finalizer(ledger: Ledger, job_id: str) -> None:
    now = utc_now()
    job = ledger.get_job(job_id)
    assert job is not None
    ledger.update_job_fields(
        job_id,
        finalizer=True,
        status="finalizing",
        current_step="cancel finalizer",
        progress=max(job.progress, 95),
        cleanup=CleanupState(
            status="destroying",
            attempts=1,
            updated_at=now,
        ),
    )
    ledger.append_event(
        job_id,
        typ="status",
        message="finalizing (cancel)",
        payload={"status": "finalizing"},
        finalizer=True,
    )
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox destroy stub (no live msb yet)",
        payload={"phase": "destroying", "reason": "cancel"},
        finalizer=True,
    )

    job = ledger.get_job(job_id)
    assert job is not None
    destroyed_at = now
    if job.current_sandbox_generation is not None:
        ledger.mark_generation_state(
            job_id,
            job.current_sandbox_generation,
            "destroyed",
            destroyed_at=destroyed_at,
        )

    ledger.update_job_fields(
        job_id,
        finalizer=True,
        cleanup=CleanupState(
            status="destroyed",
            attempts=1,
            updated_at=now,
        ),
        destroyed_at=destroyed_at,
        current_step="cancelled",
    )
    ledger.append_event(
        job_id,
        typ="lifecycle",
        message="sandbox destroyed (cancel stub)",
        payload={"phase": "destroyed", "reason": "cancel"},
        finalizer=True,
    )

    ledger.upsert_receipt(
        job_id,
        verification=job.verification,
        containment={"status": "skipped", "reason": "cancel_before_probes"},
        lifecycle={
            "cancel": True,
            "destroyed_at": destroyed_at,
            "cleanup": "destroyed",
        },
        dossier={
            "outcome": "cancelled",
            "cancel_requested_at": job.cancel_requested_at or now,
        },
    )

    ledger.update_job_fields(
        job_id,
        finalizer=True,
        status="cancelled",
        progress=100,
        current_step="cancelled",
    )
    ledger.append_event(
        job_id,
        typ="status",
        message="cancelled",
        payload={"status": "cancelled"},
        finalizer=True,
    )


def claim_pending_job() -> Job | None:
    """Background worker: pick the oldest pending job and move it to analyzing."""
    ledger = get_ledger()
    for job in ledger.list_jobs():
        if job.status != "pending":
            continue
        if job.cancel_requested_at is not None:
            continue
        try:
            updated = ledger.update_job_fields(
                job.job_id,
                status="analyzing",
                current_step="worker stub: analyzing",
                progress=5,
                steps_completed=["pending"],
            )
            ledger.append_event(
                job.job_id,
                typ="status",
                message="analyzing",
                payload={"status": "analyzing", "kind": "agent"},
            )
            ledger.append_event(
                job.job_id,
                typ="log",
                message="background worker stub claimed job (no sandbox yet)",
                payload={"kind": "agent"},
            )
            return updated
        except Ledger.WriterFrozenError:
            continue
    return None
