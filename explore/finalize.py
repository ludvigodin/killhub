"""Receipt + destroy + terminal status (E5, D37, D49, D57, D61, D66)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import Settings, get_settings
from harness import DestroyResult, destroy_job_environment
from jobs import get_ledger
from ledger.store import utc_now
from models import CleanupState
from safety import review_priority
from vulnscan import VulnScanError, collect_stream_findings, run_vuln_scan

logger = logging.getLogger("killhub.finalize")

TERMINAL = frozenset({"completed", "failed", "cancelled"})


@dataclass
class FinalizeResult:
    job_id: str
    terminal_status: str
    destroyed: bool
    destroy_failed: bool
    receipt: dict[str, Any] | None
    vuln_status: str | None


class FinalizeError(Exception):
    def __init__(self, message: str, *, code: str = "finalize_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _containment_claim(job_id: str, settings: Settings) -> dict[str, Any] | None:
    ledger = get_ledger(settings)
    # Prefer receipt already written by containment step.
    existing = ledger.get_receipt(job_id)
    if existing and existing.get("containment"):
        return existing["containment"]
    for event in reversed(ledger.list_events(job_id)):
        if event.type == "containment" and (event.payload or {}).get("claim"):
            return event.payload
    return None


def evaluate_gates(
    job_id: str,
    *,
    settings: Settings,
) -> dict[str, Any]:
    """
    D66 gate table — readiness evidence is never deleted.
    Returns {terminal, reasons, hard_fail, readiness_passed}.
    """
    ledger = get_ledger(settings)
    job = ledger.get_job(job_id)
    if job is None:
        raise FinalizeError(f"unknown job_id: {job_id}", code="not_found")

    if job.cancel_requested_at is not None:
        return {
            "terminal": "cancelled",
            "reasons": ["cancel_requested"],
            "hard_fail": False,
            "readiness_passed": bool((job.readiness or {}).get("passed")),
        }

    readiness = job.readiness or {}
    readiness_passed = bool(readiness.get("passed"))
    verification = job.verification or {}
    reasons: list[str] = []
    hard_fail = False

    # Policy bypass (guest reached CP/management) — hard fail (D66).
    for event in ledger.list_events(job_id):
        payload = event.payload or {}
        if event.type == "finding" and payload.get("classification") == "policy_bypass":
            hard_fail = True
            reasons.append("policy_bypass")
            break
        if event.type == "containment":
            dims = payload.get("dimensions") or {}
            for dim in dims.values() if isinstance(dims, dict) else []:
                if isinstance(dim, dict) and dim.get("classification") == "policy_bypass":
                    hard_fail = True
                    reasons.append("containment_policy_bypass")
                    break
            if payload.get("classification") == "policy_bypass":
                hard_fail = True
                reasons.append("containment_policy_bypass")
        if hard_fail:
            break

    if hard_fail:
        return {
            "terminal": "failed",
            "reasons": reasons,
            "hard_fail": True,
            "readiness_passed": readiness_passed,
        }

    if not readiness_passed or verification.get("kind") == "setup_failed":
        reasons.append("readiness_not_passed")
        return {
            "terminal": "failed",
            "reasons": reasons,
            "hard_fail": False,
            "readiness_passed": False,
        }

    reasons.append("readiness_passed")
    # SCA / MCP findings do not block completed (D11, D35, D66).
    return {
        "terminal": "completed",
        "reasons": reasons,
        "hard_fail": False,
        "readiness_passed": True,
    }


def finalize_job(
    job_id: str,
    *,
    settings: Settings | None = None,
    skip_scan: bool = False,
    destroy: bool = True,
) -> FinalizeResult:
    """
    scanning → vuln report → receipt → destroy → terminal (D37, D49, D57, D66).

    Receipt is always written before terminal status. Destroy confirmation only
    sets job-level destroyed_at (D57). Never clears readiness.
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise FinalizeError(f"unknown job_id: {job_id}", code="not_found")

    if job.status in TERMINAL:
        # Already terminal with confirmed destroy — nothing to do.
        if job.destroyed_at is not None or not job.sandbox_id:
            return FinalizeResult(
                job_id=job_id,
                terminal_status=job.status,
                destroyed=job.destroyed_at is not None or not job.sandbox_id,
                destroy_failed=(job.cleanup.status == "destroy_failed"),
                receipt=ledger.get_receipt(job_id),
                vuln_status=(ledger.get_vuln_report(job_id) or {}).get("status"),
            )
        # Terminal but sandbox still live (e.g. discover flipped failed before
        # finalize) — reopen to finalizing so reclaim can complete (D37).
        ledger.update_job_fields(
            job_id,
            finalizer=True,
            status="finalizing",
            current_step="reclaim after terminal without destroy",
        )
        job = ledger.get_job(job_id)
        assert job is not None

    # Preserve readiness snapshot before any finalizer writes.
    readiness_before = dict(job.readiness) if job.readiness else None

    vuln_status: str | None = None
    scan_error: str | None = None
    if not skip_scan:
        try:
            scan = run_vuln_scan(job_id, settings=cfg)
            vuln_status = scan.status
        except VulnScanError as exc:
            scan_error = exc.message
            vuln_status = "failed"
            ledger.upsert_vuln_report(
                job_id,
                summary=f"Scan aborted: {exc.message}",
                findings=collect_stream_findings(job_id, cfg),
                status="failed",
                finalizer=True,
            )
            ledger.append_event(
                job_id,
                typ="error",
                message=exc.message,
                payload={"code": exc.code, "phase": "vulnscan"},
                finalizer=True,
            )
        except Exception as exc:  # noqa: BLE001
            scan_error = exc.__class__.__name__
            vuln_status = "failed"
            logger.exception("vulnscan crashed for %s", job_id)
            ledger.upsert_vuln_report(
                job_id,
                summary=f"Scanner crash ({exc.__class__.__name__}); report partial.",
                findings=collect_stream_findings(job_id, cfg),
                status="failed",
                finalizer=True,
            )

    gates = evaluate_gates(job_id, settings=cfg)
    terminal = str(gates["terminal"])

    job = ledger.get_job(job_id)
    assert job is not None
    # Never clear readiness (D11 / D66).
    if readiness_before and job.readiness != readiness_before:
        ledger.update_job_fields(
            job_id,
            finalizer=True,
            readiness=readiness_before,
        )

    ledger.update_job_fields(
        job_id,
        finalizer=True,
        status="finalizing",
        current_step="finalizing receipt + cleanup",
        progress=max(job.progress, 98),
        cleanup=CleanupState(
            status="destroying" if destroy and job.sandbox_id else job.cleanup.status,
            attempts=max(job.cleanup.attempts, 1),
            updated_at=utc_now(),
        ),
    )
    ledger.append_event(
        job_id,
        typ="status",
        message="finalizing",
        payload={"status": "finalizing", "gates": gates},
        finalizer=True,
    )

    destroy_result = DestroyResult(confirmed=True, error=None)
    if destroy and job.sandbox_id:
        destroy_result = destroy_job_environment(
            job_id,
            reason="finalize",
            settings=cfg,
            finalizer=True,
        )
    elif not job.sandbox_id:
        ledger.append_event(
            job_id,
            typ="lifecycle",
            message="no live sandbox to destroy",
            payload={"phase": "destroyed", "reason": "finalize", "confirmed": True},
            finalizer=True,
        )

    destroyed_at = utc_now() if destroy_result.confirmed else None
    cleanup_status = "destroyed" if destroy_result.confirmed else "destroy_failed"

    # Re-read after destroy (generation fields may have updated).
    job = ledger.get_job(job_id)
    assert job is not None
    # Restore readiness if destroy path somehow cleared it.
    if readiness_before and not job.readiness:
        ledger.update_job_fields(job_id, finalizer=True, readiness=readiness_before)
        job = ledger.get_job(job_id)
        assert job is not None

    vuln_report = ledger.get_vuln_report(job_id)
    containment = _containment_claim(job_id, cfg)
    generations = [
        {
            "generation": g.generation,
            "environment_id": g.environment_id,
            "image": g.image,
            "state": g.state,
            "destroyed_at": g.destroyed_at,
            "expires_at": g.expires_at,
        }
        for g in ledger.list_sandbox_generations(job_id)
    ]
    revisions = [
        {
            "revision": r.revision,
            "phase": r.phase,
            "schema_version": r.schema_version,
        }
        for r in ledger.list_profile_revisions(job_id)
    ]

    # Keep measured coverage even when the checks produced no findings.
    active_checks: dict[str, Any] = {"install_trace": None, "mcp_tools_reviewed": None}
    for event in ledger.list_events(job_id):
        payload = event.payload or {}
        if event.type != "log":
            continue
        if payload.get("kind") == "install_activity":
            active_checks["install_trace"] = payload.get("coverage")
        elif payload.get("kind") == "mcp_tool_review":
            active_checks["mcp_tools_reviewed"] = payload.get("tool_count")
    active_findings = [
        f
        for f in (vuln_report or {}).get("findings") or []
        if f.get("source") in {"activity", "mcp_tool_review"}
    ]
    active_checks["finding_count"] = len(active_findings)
    leading = min(active_findings, key=review_priority, default=None)
    active_checks["leading_finding"] = (
        {k: leading[k] for k in ("id", "severity", "source", "title")} if leading else None
    )

    dossier = {
        "outcome": terminal,
        "active_checks": active_checks,
        "gates": gates,
        "vuln_report_status": vuln_status or (vuln_report or {}).get("status"),
        "scan_error": scan_error,
        "profile_revisions": revisions,
        "sandbox_generations": generations,
        "readiness": readiness_before or job.readiness,
        "verification": job.verification,
        "mcp_assessment": (vuln_report or {}).get("mcp_assessment"),
        "finding_ids": [f.get("id") for f in (vuln_report or {}).get("findings") or []],
        "vuln_review": (vuln_report or {}).get("summary"),
        "at": utc_now(),
    }

    # Receipt BEFORE terminal status (D49, D61).
    receipt = ledger.upsert_receipt(
        job_id,
        verification=job.verification,
        containment=containment,
        lifecycle={
            "destroyed_at": destroyed_at,
            "cleanup": cleanup_status,
            "destroy_error": destroy_result.error,
            "confirmed": destroy_result.confirmed,
        },
        dossier=dossier,
    )

    ledger.update_job_fields(
        job_id,
        finalizer=True,
        cleanup=CleanupState(
            status=cleanup_status,
            attempts=max(job.cleanup.attempts, 1),
            last_error=destroy_result.error,
            updated_at=utc_now(),
        ),
        destroyed_at=destroyed_at,
        # readiness unchanged
        readiness=readiness_before or job.readiness,
        current_step=f"terminal {terminal}",
    )

    ledger.update_job_fields(
        job_id,
        finalizer=True,
        status=terminal,  # type: ignore[arg-type]
        progress=100,
        current_step=terminal,
        error=None if terminal == "completed" else (job.error or "; ".join(gates["reasons"])),
    )
    ledger.append_event(
        job_id,
        typ="status",
        message=terminal,
        payload={
            "status": terminal,
            "gates": gates,
            "cleanup": cleanup_status,
            "destroyed_at": destroyed_at,
        },
        finalizer=True,
    )
    try:
        from service import release_admission_slot

        # Finalize runs after claim → always releasing a running slot (D71).
        release_admission_slot(was_running=True)
    except Exception:  # noqa: BLE001 — admission must not block terminal
        pass

    return FinalizeResult(
        job_id=job_id,
        terminal_status=terminal,
        destroyed=bool(destroyed_at),
        destroy_failed=cleanup_status == "destroy_failed",
        receipt=receipt,
        vuln_status=vuln_status,
    )
