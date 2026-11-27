"""Public projections of active-check evidence, including receipts from older workers."""

from typing import Any

from models import JobEvent
from safety import review_priority

CHECK_LABELS = {
    "canary_exfiltration": "Test secret in outgoing traffic",
    "persistence_write": "Writes to persistence locations",
    "install_network_tools": "Network tools used during installation",
    "mcp_tool_poisoning": "Suspicious MCP tool descriptions",
}
ACTIVE_SOURCES = {"activity", "mcp_tool_review"}


def active_finding(event: JobEvent) -> dict[str, Any]:
    payload = event.payload or {}
    code = payload.get("code") or payload["source"]
    # Canary findings carry an outcome-specific message (activity.CANARY_OUTCOME_TITLES);
    # events from older workers keep their original wording.
    title = event.message
    if code == "install_network_tools" and not payload.get("repository_steps_only"):
        title = (
            "Network tooling ran during installation. This trace does not distinguish "
            "project steps from Killhub setup steps."
        )
    return {
        "id": f"{code}-{event.event_id}",
        "source": payload["source"],
        "severity": payload.get("severity") or "medium",
        "title": title,
        "detail": {k: v for k, v in payload.items() if k not in {"finding", "excerpt"}},
    }


def group_active_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for finding in sorted(findings, key=review_priority):
        if finding.get("source") not in ACTIVE_SOURCES:
            continue
        detail = finding.get("detail") or {}
        code = detail.get("code") or finding["source"]
        group = groups.setdefault(
            code,
            {
                "check": code,
                "label": CHECK_LABELS.get(code, "Other active check"),
                "count": 0,
                "finding_id": finding["id"],
                "severity": finding.get("severity"),
            },
        )
        group["count"] += 1
    return list(groups.values())


def with_active_summary(summary: str, findings: list[dict[str, Any]]) -> str:
    groups = group_active_findings(findings)
    if not groups:
        return summary
    parts = [f"{g['label']} ({g['count']}) [{g['finding_id']}]" for g in groups]
    return f"{summary} Active checks: {', '.join(parts)}."


def summarize_active_checks(
    events: list[JobEvent], findings: list[dict[str, Any]]
) -> dict[str, Any]:
    # Keep measured coverage even when the checks produced no findings.
    active_checks: dict[str, Any] = {"install_trace": None, "mcp_tools_reviewed": None}
    for event in events:
        payload = event.payload or {}
        if event.type != "log":
            continue
        if payload.get("kind") == "install_activity":
            active_checks["install_trace"] = (
                "none" if payload.get("trace_bytes") == 0 else payload.get("coverage")
            )
        elif payload.get("kind") == "mcp_tool_review":
            active_checks["mcp_tools_reviewed"] = payload.get("tool_count")
    active_findings = [f for f in findings if f.get("source") in ACTIVE_SOURCES]
    active_checks["by_check"] = group_active_findings(active_findings)
    active_checks["finding_count"] = len(active_findings)
    leading = min(active_findings, key=review_priority, default=None)
    active_checks["leading_finding"] = (
        {k: leading[k] for k in ("id", "severity", "source", "title")} if leading else None
    )

    return active_checks
