"""Job-facing services over the ledger (create / cancel / snapshot) — D52 / D61."""

from __future__ import annotations

import logging
from typing import Any

from admission import (
    AdmissionRejected,
    AdmissionStoreError,
    get_admission_store,
)
from config import Settings, get_settings
from fixtures import match_fixture
from git_url import validate_public_git_url
from jobs import get_ledger
from ledger import Ledger
from ledger.store import utc_now
from models import CleanupState, Job

logger = logging.getLogger("killhub.admission")

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


def _raise_admission(exc: AdmissionRejected | AdmissionStoreError) -> None:
    if isinstance(exc, AdmissionStoreError):
        raise AdmissionError(
            "Admission store unavailable",
            code="admission_unavailable",
            status_code=503,
        ) from exc
    raise AdmissionError(exc.message, code=exc.code, status_code=exc.status_code) from exc


def _ledger_capacity_full(cfg: Settings) -> bool:
    ledger = get_ledger(cfg)
    jobs = ledger.list_jobs()
    running = sum(1 for j in jobs if j.status in RUNNING_STATUSES)
    queued = sum(1 for j in jobs if j.status in QUEUED_STATUSES)
    capacity = cfg.max_concurrent_jobs + cfg.max_queued_jobs
    active = running + queued
    if active >= capacity:
        return True
    if running >= cfg.max_concurrent_jobs and queued >= cfg.max_queued_jobs:
        return True
    return False


def _enforce_admission(
    cfg: Settings,
    *,
    client_ip: str | None = None,
) -> None:
    """Reject create when concurrency / queue / rate / budget gates fire (D40, D71)."""
    store = get_admission_store(cfg)
    try:
        store.ping()
    except AdmissionStoreError as exc:
        _raise_admission(exc)

    if cfg.inference_budget_reject:
        raise AdmissionError(
            "Inference budget exhausted",
            code="inference_budget",
            status_code=429,
        )

    try:
        store.check_rolling_inference(
            tokens=0,
            budget=cfg.inference_budget_tokens_rolling,
            window_seconds=cfg.inference_budget_rolling_window_seconds,
        )
        # Per-IP / global POST rate limits: Next.js edge (D40). Explore owns
        # concurrency / queue + rolling inference. client_ip is accepted for
        # future Internal API throttling without double-counting edge hits.
        _ = client_ip
        if store.backend == "valkey":
            store.try_admit(
                max_concurrent=cfg.max_concurrent_jobs,
                max_queued=cfg.max_queued_jobs,
            )
        elif _ledger_capacity_full(cfg):
            raise AdmissionRejected(
                "Job concurrency and queue are full",
                code="queue_full",
                status_code=503,
            )
    except (AdmissionRejected, AdmissionStoreError) as exc:
        _raise_admission(exc)


def release_admission_slot(
    *,
    was_running: bool,
    settings: Settings | None = None,
) -> None:
    """Best-effort slot release for Valkey-backed counters (D71)."""
    cfg = settings or get_settings()
    store = get_admission_store(cfg)
    if store.backend != "valkey":
        return
    store.on_terminal(was_running=was_running)


def create_job(
    github_url: str,
    *,
    settings: Settings | None = None,
    client_ip: str | None = None,
) -> Job:
    """Admit + create ledger row, then Plane-1 pre-flight (D45) before any msb."""
    from preflight import apply_preflight_to_job, run_preflight

    cfg = settings or get_settings()
    if cfg.public_demo_fixtures_only:
        github_url = validate_public_git_url(github_url)
        fixture = match_fixture(github_url)
        if not fixture or not fixture.get("public_demo") or not fixture.get("commit"):
            raise AdmissionError(
                "Demo intake accepts only the three pinned Killhub SCA fixture repositories.",
                "demo_fixture_required",
                403,
            )
    _enforce_admission(cfg, client_ip=client_ip)
    ledger = get_ledger(cfg)
    try:
        job = ledger.create_job(github_url, env_ttl_seconds=cfg.env_ttl_seconds)
    except Exception:
        # Undo Valkey queue reservation if ledger create fails.
        release_admission_slot(was_running=False, settings=cfg)
        raise
    result = run_preflight(job.github_url, settings=cfg)
    if not result.meta.get("skipped"):
        apply_preflight_to_job(job.job_id, result, settings=cfg)
    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    # Preflight may terminal-fail the job before claim — release queued slot.
    if refreshed.status in TERMINAL:
        release_admission_slot(was_running=False, settings=cfg)
    return refreshed


def get_public_snapshot(job_id: str) -> dict[str, Any] | None:
    return get_ledger().get_snapshot(job_id)


def _job_summary_dict(
    job: Job,
    *,
    ledger: Ledger,
    settings: Settings,
) -> dict[str, Any]:
    shots = ledger.list_screenshots(job.job_id)
    latest_shot = shots[-1] if shots else None
    latest = latest_shot["screenshot_id"] if latest_shot else None
    screenshot_url: str | None = None
    if latest_shot is not None and latest:
        from screenshots import public_screenshot_url

        screenshot_url = public_screenshot_url(
            job.job_id,
            str(latest),
            storage_path=str(latest_shot.get("storage_path") or "") or None,
            settings=settings,
        )
    return {
        "job_id": job.job_id,
        "github_url": job.github_url,
        "status": job.status,
        "progress": job.progress,
        "current_step": job.current_step,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "screenshot_id": latest,
        "screenshot_url": screenshot_url,
        "error": job.error,
        "verification": job.verification,
    }


def list_job_summaries(
    *,
    limit: int = 48,
    offset: int = 0,
    github_url: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Recent jobs — summary fields only (D69 / D77). Optional github_url filter (D79)."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    if github_url is not None:
        jobs = ledger.list_jobs_for_url(github_url, limit=limit, offset=offset)
    else:
        jobs = ledger.list_recent_jobs(limit=limit, offset=offset)
    return [_job_summary_dict(job, ledger=ledger, settings=cfg) for job in jobs]


def list_jobs_page(
    *,
    limit: int = 48,
    offset: int = 0,
    github_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Paginated job list with total count (D77). Optional github_url filter (D79)."""
    cfg = settings or get_settings()
    capped_limit = max(1, min(int(limit), 200))
    capped_offset = max(0, int(offset))
    ledger = get_ledger(cfg)
    if github_url is not None:
        total = ledger.count_jobs_for_url(github_url)
    else:
        total = ledger.count_jobs()
    jobs = list_job_summaries(
        limit=capped_limit,
        offset=capped_offset,
        github_url=github_url,
        settings=cfg,
    )
    return {
        "jobs": jobs,
        "total": total,
        "limit": capped_limit,
        "offset": capped_offset,
    }


def list_repos_page(
    *,
    limit: int = 48,
    offset: int = 0,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Paginated repo groups: one latest job + run_count per github_url (D79)."""
    cfg = settings or get_settings()
    capped_limit = max(1, min(int(limit), 200))
    capped_offset = max(0, int(offset))
    ledger = get_ledger(cfg)
    total = ledger.count_repos()
    repos: list[dict[str, Any]] = []
    for job, run_count in ledger.list_recent_repos(limit=capped_limit, offset=capped_offset):
        repos.append(
            {
                "github_url": job.github_url,
                "run_count": run_count,
                "latest": _job_summary_dict(job, ledger=ledger, settings=cfg),
            }
        )
    return {
        "repos": repos,
        "total": total,
        "limit": capped_limit,
        "offset": capped_offset,
    }


def cancel_job(job_id: str) -> dict[str, Any]:
    """
    D61 cancel: request → freeze → finalizer (receipt + destroy) → terminal cancelled.

    Live generations are destroyed via harness/`msb` (D57). Jobs with no sandbox
    generation complete cleanup without inventing a Plane 2 destroy.
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
    from harness import DestroyResult, destroy_environment

    now = utc_now()
    job = ledger.get_job(job_id)
    assert job is not None
    # Capture before status → finalizing so Valkey release picks queued vs running.
    was_running = job.status in RUNNING_STATUSES or job.status == "finalizing"
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

    destroy_result = DestroyResult(confirmed=True, error=None)
    if job.sandbox_id and job.current_sandbox_generation is not None:
        destroy_result = destroy_environment(
            job.sandbox_id,
            job_id=job_id,
            reason="cancel",
            finalizer=True,
        )
    else:
        ledger.append_event(
            job_id,
            typ="lifecycle",
            message="no live sandbox to destroy",
            payload={"phase": "destroyed", "reason": "cancel", "confirmed": True},
            finalizer=True,
        )

    job = ledger.get_job(job_id)
    assert job is not None
    destroyed_at = utc_now() if destroy_result.confirmed else None
    cleanup_status = "destroyed" if destroy_result.confirmed else "destroy_failed"
    prior_receipt = ledger.get_receipt(job_id) or {}
    # Keep completed probes and persist the cancelled verdict with terminal state.
    ledger.finalize_job(
        job_id,
        status="cancelled",
        include_verdict=True,
        receipt={
            "verification": job.verification,
            "containment": prior_receipt.get("containment")
            or {"status": "skipped", "reason": "cancel_before_probes"},
            "lifecycle": {
                "cancel": True,
                "destroyed_at": destroyed_at,
                "cleanup": cleanup_status,
                "destroy_error": destroy_result.error,
            },
            "dossier": {
                **(prior_receipt.get("dossier") or {}),
                "outcome": "cancelled",
                "cancel_requested_at": job.cancel_requested_at or now,
            },
        },
        cleanup=CleanupState(
            status=cleanup_status,
            attempts=1,
            last_error=destroy_result.error,
            updated_at=utc_now(),
        ),
        destroyed_at=destroyed_at,
        current_step="cancelled",
        progress=100,
    )
    release_admission_slot(was_running=was_running)


def claim_pending_job() -> Job | None:
    """Background worker: pick the oldest pending job and move it to analyzing."""
    cfg = get_settings()
    ledger = get_ledger(cfg)
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
                message="background worker claimed job",
                payload={"kind": "agent"},
            )
            store = get_admission_store(cfg)
            if store.backend == "valkey":
                store.on_claimed()
            return updated
        except Ledger.WriterFrozenError:
            continue
    return None
