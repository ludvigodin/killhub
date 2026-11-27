"""Slim security-outcome enum for job list summaries (feed stamps)."""

from __future__ import annotations

from typing import Any, Literal

SafetyOutcome = Literal["safe", "high_risk", "review", "unknown"]

_TERMINAL = frozenset({"completed", "failed", "cancelled"})

# Frontend securityVerdict treats this summary as incomplete coverage.
_CLEAN_BILL_SUMMARY = "No scan findings. Clean bill for this job's scanned surfaces."


def _severity_counts(findings: list[Any] | None) -> dict[str, int]:
    counts = {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
        "unknown": 0,
        "other": 0,
        "missing_severity": 0,
    }
    if not isinstance(findings, list):
        return counts
    for item in findings:
        if not isinstance(item, dict):
            counts["other"] += 1
            continue
        raw = item.get("severity")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            counts["missing_severity"] += 1
            continue
        sev = str(raw).lower()
        if sev == "moderate":
            sev = "medium"
        if sev == "unknown":
            counts["unknown"] += 1
        elif sev in counts:
            counts[sev] += 1
        else:
            counts["other"] += 1
    return counts


def summary_safety(
    *,
    status: str,
    verification: dict[str, Any] | None,
    vuln_report: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
) -> SafetyOutcome | None:
    """Return a short safety stamp for list cards, or None while still running.

    Mirrors frontend ``securityVerdict`` gates. Non-terminal jobs and jobs
    without a receipt stay ``None`` so the UI keeps the pipeline StatusBadge.
    """
    if status not in _TERMINAL or receipt is None:
        return None

    findings = None
    if isinstance(vuln_report, dict):
        findings = vuln_report.get("findings")
    counts = _severity_counts(findings if isinstance(findings, list) else None)

    dossier = receipt.get("dossier") if isinstance(receipt, dict) else None
    gates = dossier.get("gates") if isinstance(dossier, dict) else None
    reasons = gates.get("reasons") if isinstance(gates, dict) else None
    bypass = isinstance(reasons, list) and any(
        r in {"policy_bypass", "containment_policy_bypass"} for r in reasons
    )

    verify = verification
    if not isinstance(verify, dict):
        verify = receipt.get("verification") if isinstance(receipt, dict) else None
    target = verify.get("kind") if isinstance(verify, dict) else None

    gaps = False
    if not isinstance(vuln_report, dict):
        gaps = True
    else:
        report_status = vuln_report.get("status")
        report_findings = vuln_report.get("findings")
        report_summary = vuln_report.get("summary")
        if (
            report_status != "ok"
            or not isinstance(report_findings, list)
            or report_summary == _CLEAN_BILL_SUMMARY
        ):
            gaps = True

    if target == "generated_demo":
        gaps = True
    elif target != "original_application" or status != "completed":
        gaps = True

    containment = receipt.get("containment") if isinstance(receipt, dict) else None
    claim = containment.get("claim") if isinstance(containment, dict) else None
    if claim != "proven":
        gaps = True

    if bypass or counts["critical"] or counts["high"]:
        return "high_risk"
    if (
        counts["medium"]
        or counts["low"]
        or counts["other"]
        or counts["unknown"]
        or counts["missing_severity"]
    ):
        return "review"
    if gaps:
        return "unknown"
    return "safe"


def review_priority(finding: dict[str, Any]) -> int:
    # unknown / missing sort after low so known severities win enrichment pick order.
    rank = {
        "critical": 0,
        "high": 1,
        "medium": 2,
        "moderate": 2,
        "low": 3,
        "unknown": 4,
        "info": 5,
    }
    sev = str(finding.get("severity") or "unknown").lower()
    return rank.get(sev, 4)
