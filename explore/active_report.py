"""Public projections of active-check evidence, including receipts from older workers."""

from typing import Any

from models import JobEvent
from safety import review_priority

ACTIVE_SOURCES = {"activity", "mcp_tool_review"}


def active_finding(event: JobEvent) -> dict[str, Any]:
    payload = event.payload or {}
    code = payload.get("code") or payload["source"]
    title = event.message
    if code == "canary_exfiltration":
        title = "The install trace matched a test secret in an outgoing network attempt"
    return {
        "id": f"{code}-{event.event_id}",
        "source": payload["source"],
        "severity": payload.get("severity") or "medium",
        "title": title,
        "detail": {k: v for k, v in payload.items() if k not in {"finding", "excerpt"}},
    }


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
    active_checks["finding_count"] = len(active_findings)
    leading = min(active_findings, key=review_priority, default=None)
    active_checks["leading_finding"] = (
        {k: leading[k] for k in ("id", "severity", "source", "title")} if leading else None
    )

    return active_checks
