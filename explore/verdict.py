"""Plane 1 verdict projection from durable job, scan, and containment evidence.

The public report carries observed facts. Missing sensors, integrity hashes,
and risk scores remain explicitly unknown, including for older workers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from models import Job, JobStatus

_ATLAS_NAMES = (
    "AI Model Access",
    "AI Attack Adaptation",
    "Reconnaissance",
    "Resource Development",
    "Initial Access",
    "Execution",
    "Persistence",
    "Defense Evasion",
    "Discovery",
    "Collection",
    "Exfiltration",
    "Impact",
    "Privilege Escalation",
    "Credential Access",
    "Lateral Movement",
    "Command and Control",
)
_MCP_NAMES = (
    "Token Mismanagement & Secret Exposure",
    "Privilege Escalation via Scope Creep",
    "Tool Poisoning",
    "Software Supply Chain Attacks & Dependency Tampering",
    "Command Injection & Execution",
    "Prompt Injection via Contextual Payloads",
    "Insufficient Authentication & Authorization",
    "Lack of Audit and Telemetry",
    "Shadow MCP Servers",
    "Context Injection & Over-Sharing",
)
_AXES = ("timeout_enforcement", "host_access_denied", "sibling_access_denied", "host_liveness")
_SOURCE_SENSORS = {"sca": "sca_scanner", "preflight": "preflight", "canary": "canary_monitor"}


@lru_cache(maxsize=1)
def verdict_validator() -> Draft202012Validator:
    """Load the canonical schema from the worker image as well as the source tree."""
    path = Path(__file__).resolve().parent / "schemas" / "detonation_verdict.v1.json"
    return Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))


def _axis_result(axis: str, raw: Any) -> dict[str, Any]:
    # Probe detail often contains internal addresses or command output. Publish
    # the stored classification without copying the underlying payload.
    if not isinstance(raw, dict):
        return {"status": "not_tested", "detail": "No probe result recorded."}
    classification = raw.get("classification")
    status = "inconclusive"
    if classification in ("infra_error", "tooling_missing"):
        status = classification
    elif classification == "policy_bypass":
        status = "failed"
    elif raw.get("ok") is True:
        if axis in ("timeout_enforcement", "host_liveness"):
            status = "passed"
        elif classification == "policy_denied":
            status = "policy_denied"
    return {"status": status, "detail": f"Recorded probe outcome: {status.replace('_', ' ')}."}


def _findings(report: dict[str, Any], dossier: dict[str, Any]) -> list[dict[str, Any]]:
    from inference_extras import redact_inference_text

    permitted = verdict_validator().schema["$defs"]["DetonationFinding"]["properties"]
    summary = report.get("summary") or ""
    by_id: dict[str, dict[str, Any]] = {}
    # Preflight can persist evidence before a vulnerability report exists.
    for item in [*(dossier.get("findings") or []), *(report.get("findings") or [])]:
        if not isinstance(item, dict) or item.get("source") not in permitted["source"]["enum"]:
            continue
        raw_id = item.get("id") or item.get("code")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        public_id = redact_inference_text(raw_id).strip()[:120]
        source = item["source"]
        severity = str(item.get("severity") or "info").lower()
        if severity not in permitted["severity"]["enum"]:
            severity = "info"
        title = redact_inference_text(str(item.get("title") or item.get("message") or public_id))
        by_id[public_id] = {
            "id": public_id,
            "severity": severity,
            "source": source,
            "atlas_tactic": None,
            # A dependency advisory is evidence for the supply-chain category.
            "owasp_mcp": "MCP04:2025" if source == "sca" else None,
            "sensor": _SOURCE_SENSORS.get(source),
            "title": title.strip()[:500] or public_id,
            "detail": "See the job's recorded findings for details.",
            "evidence": {},
            "blocked": source == "preflight" and item.get("hard") is True,
            "cited_by_review": f"[{raw_id}]" in summary,
        }
    return list(by_id.values())


def build_verdict(
    job: Job,
    status: JobStatus,
    receipt: dict[str, Any],
    vuln_report: dict[str, Any] | None,
    *,
    integrity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and validate a v1 verdict for the evidence currently produced by Killhub."""
    report = vuln_report or {}
    dossier = receipt.get("dossier") or {}
    dimensions = (receipt.get("containment") or {}).get("dimensions") or {}
    axes = {name: _axis_result(name, dimensions.get(name)) for name in _AXES}
    findings = _findings(report, dossier)
    sca_ids = [item["id"] for item in findings if item["source"] == "sca"]
    integrity = integrity or {}
    digest_before = integrity.get("digest_before")
    digest_after = integrity.get("digest_after")
    compared = digest_before is not None and digest_after is not None
    changed = digest_before != digest_after if compared else None
    supply_chain_ids = list(sca_ids)
    if changed:
        # A change is evidence about checkout integrity, regardless of install intent.
        finding_id = "checkout-changed-after-install"
        findings.append(
            {
                "id": finding_id,
                "severity": "medium",
                "source": "runtime_sensor",
                "atlas_tactic": None,
                "owasp_mcp": "MCP04:2025",
                "sensor": "checkout_sha256",
                "title": "Tracked checkout changed during install",
                "detail": "Review the changes against the expected install behavior.",
                "evidence": {"scope": "pinned_git_paths"},
                "blocked": False,
                "cited_by_review": False,
            }
        )
        supply_chain_ids.append(finding_id)

    bypass = any(axes[name]["status"] == "failed" for name in _AXES)
    if bypass:
        label, summary = "SUSPICIOUS", "A recorded containment probe reported a policy bypass."
    elif status == "cancelled" or (status == "failed" and not (job.readiness or {}).get("passed")):
        label, summary = "ABORTED", "The job stopped before runtime assessment could be completed."
    else:
        label, summary = "INCONCLUSIVE", "Runtime assessment evidence is incomplete."

    validator = verdict_validator()
    atlas_ids = validator.schema["$defs"]["AtlasTacticId"]["enum"]
    mcp_ids = validator.schema["$defs"]["OwaspMcpId"]["enum"]
    sca_observed = bool(sca_ids) or report.get("status") == "ok"
    supply_chain_sensors = ["sca_scanner"] if sca_observed else []
    if compared:
        supply_chain_sensors.append("checkout_sha256")
    result = {
        "schema_version": "1",
        "scan_id": job.job_id,
        "target": {
            # The ledger retains the legacy field name for all supported git hosts.
            "source_type": (
                "github_repo" if urlsplit(job.github_url).hostname == "github.com" else "git_repo"
            ),
            "locator": job.github_url,
            "resolved_ref": job.resolved_commit,
            "package_sha256_before": digest_before,
            "package_sha256_after": digest_after,
            "integrity_tampered": changed,
        },
        "verdict": {
            "status": label,
            "risk_score": None,
            "summary": summary,
            "kill_switch_triggered": {
                "triggered": False,
                "layer": None,
                "reason": None,
                "timestamp": None,
            },
        },
        "containment_proof": {
            **axes,
            # The current probe matrix does not include the aligned runtime sensors.
            "claim": "incomplete",
            "key_isolation_verified": False,
            "canary_blocking_verified": False,
            "doh_dot_quic_dropped": False,
        },
        "mcp_capabilities": {
            "discovery_method": "none",
            "t0_tools_sha256": None,
            "final_tools_sha256": None,
            "tool_diffs": [],
            "tools_count_t0": 0,
            "tools_count_final": 0,
            "resources_count": 0,
            "prompts_count": 0,
        },
        "findings": findings,
        "atlas_coverage_matrix": {
            key: {
                "tactic_id": key,
                "tactic_name": name,
                "monitored": False,
                "sensors": [],
                "triggered": False,
                "finding_ids": [],
            }
            for key, name in zip(atlas_ids, _ATLAS_NAMES, strict=True)
        },
        "owasp_mcp_coverage": {
            key: {
                "category_id": key,
                "name": name,
                "monitored": key == "MCP04:2025" and bool(supply_chain_sensors),
                "sensors": supply_chain_sensors if key == "MCP04:2025" else [],
                "triggered": key == "MCP04:2025" and bool(supply_chain_ids),
                "finding_ids": supply_chain_ids if key == "MCP04:2025" else [],
            }
            for key, name in zip(mcp_ids, _MCP_NAMES, strict=True)
        },
        # These counters describe recorded telemetry. A zero is not a coverage claim.
        "telemetry": {
            "http_requests": 0,
            "https_intercepted": 0,
            "dns_queries": 0,
            "doh_dot_quic_blocked": 0,
            "canary_blocks": 0,
            "strace_syscalls_flagged": 0,
            "overlayfs_modified_paths": [],
            "mcp_wire_messages": 0,
            "cgroup_events": {"oom": 0, "pid_max": 0, "cpu_throttled": 0},
            "llm_proxy_turns": 0,
            "llm_proxy_tokens": 0,
            "llm_proxy_429_blocks": 0,
            "pcap_artifact_path": None,
            "ndjson_events_count": 0,
        },
    }
    validator.validate(result)
    return result
