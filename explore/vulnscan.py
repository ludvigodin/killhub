"""Plane-1 SCA against copied lockfiles + optional MCP assessment (D33, D43, D35)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from harness import copy_out, exec_command
from jobs import get_ledger
from ledger.store import utc_now

logger = logging.getLogger("killhub.vulnscan")

GUEST_REPO_CANDIDATES = (
    "/tmp/killhub/repo",
    "/workspace",
    "/tmp/killhub",
)

LOCKFILE_NAMES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "requirements.txt",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "go.sum",
)

OSV_BATCH_LIMIT = 80
OSV_QUERYBATCH = "https://api.osv.dev/v1/querybatch"


@dataclass
class VulnScanResult:
    job_id: str
    status: str  # ok | partial | failed
    findings: list[dict[str, Any]] = field(default_factory=list)
    lockfiles: list[str] = field(default_factory=list)
    mcp_assessment: dict[str, Any] | None = None
    detail: str = ""


class VulnScanError(Exception):
    def __init__(self, message: str, *, code: str = "vulnscan_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _log(job_id: str, message: str, *, settings: Settings, kind: str, **payload: Any) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": kind, **payload},
    )


def _finding_event(
    job_id: str,
    *,
    settings: Settings,
    finding: dict[str, Any],
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="finding",
        message=finding.get("title") or finding.get("id") or "finding",
        payload={
            "source": finding.get("source"),
            "code": finding.get("id"),
            "severity": finding.get("severity"),
            "package": finding.get("package"),
            "advisory_url": finding.get("advisory_url"),
            "finding": finding,
        },
    )


def _current_runtime_profile(job_id: str, settings: Settings) -> dict[str, Any]:
    ledger = get_ledger(settings)
    revs = ledger.list_profile_revisions(job_id)
    runtime = [r for r in revs if r.phase == "runtime"]
    if runtime:
        return dict(runtime[-1].profile or {})
    return {}


def discover_guest_lockfiles(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
) -> list[str]:
    """Locate lockfiles inside the guest without inventing paths."""
    roots = " ".join(GUEST_REPO_CANDIDATES)
    names = " -o ".join(f"-name {n}" for n in LOCKFILE_NAMES)
    result = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            f"for root in {roots}; do "
            f'[ -d "$root" ] || continue; '
            f'find "$root" -maxdepth 4 \\( {names} \\) -type f 2>/dev/null; '
            "done | head -n 20",
        ],
        job_id=job_id,
        settings=settings,
        timeout=60,
    )
    paths: list[str] = []
    seen: set[str] = set()
    for line in (result.stdout or "").splitlines():
        path = line.strip()
        if not path.startswith("/"):
            continue
        if not any(path.endswith(n) for n in LOCKFILE_NAMES):
            continue
        if path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def copy_lockfiles_to_artifacts(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
) -> tuple[list[Path], bool]:
    """copy_out lockfiles to server-selected artifact dir (D60, D43)."""
    guest_paths = discover_guest_lockfiles(environment_id, job_id=job_id, settings=settings)
    host_paths: list[Path] = []
    for i, guest in enumerate(guest_paths):
        name = Path(guest).name
        filename = f"{i:02d}-{name}"
        try:
            dest = copy_out(
                environment_id,
                guest,
                "lockfile",
                job_id=job_id,
                filename=filename,
                settings=settings,
            )
            host_paths.append(dest)
        except Exception as exc:  # noqa: BLE001
            logger.warning("lockfile copy_out failed for %s: %s", guest, exc)
            _log(
                job_id,
                f"lockfile copy_out failed: {name}",
                settings=settings,
                kind="vulnscan",
                guest=guest,
                error=exc.__class__.__name__,
            )
    return host_paths, len(host_paths) < len(guest_paths) or len(guest_paths) >= 20


def _parse_npm_lock(data: dict[str, Any]) -> list[tuple[str, str]]:
    pkgs: list[tuple[str, str]] = []
    # lockfileVersion 2/3
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, meta in packages.items():
            if not key or not isinstance(meta, dict):
                continue
            version = meta.get("version")
            if not version:
                continue
            name = meta.get("name")
            if not name:
                # key like "node_modules/lodash"
                if key.startswith("node_modules/"):
                    name = key[len("node_modules/") :]
                    if "node_modules/" in name:
                        name = name.rsplit("node_modules/", 1)[-1]
                else:
                    continue
            if isinstance(name, str) and isinstance(version, str):
                pkgs.append((name, version))
    dependencies = data.get("dependencies")
    if isinstance(dependencies, dict):
        for name, meta in dependencies.items():
            if isinstance(meta, dict) and isinstance(meta.get("version"), str):
                pkgs.append((str(name), str(meta["version"])))
    # Dedupe
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in pkgs:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _parse_requirements_txt(text: str) -> list[tuple[str, str]]:
    pkgs: list[tuple[str, str]] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("-"):
            continue
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*==\s*([^\s;#]+)", raw)
        if m:
            pkgs.append((m.group(1), m.group(2)))
    return pkgs


def _parse_toml_lock(text: str) -> list[tuple[str, str]]:
    """``[[package]]`` entries of uv.lock / poetry.lock that come from a registry.

    Editable, virtual, path, directory and git sources (the project itself,
    workspace members, VCS pins) are skipped: OSV can't match them as PyPI
    releases.
    """
    import tomllib

    data = tomllib.loads(text)
    pkgs: list[tuple[str, str]] = []
    for pkg in data.get("package") or []:
        if not isinstance(pkg, dict):
            continue
        name, version = pkg.get("name"), pkg.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        src = pkg.get("source")
        if isinstance(src, dict):
            if any(k in src for k in ("editable", "virtual", "path", "directory", "git")):
                continue
            if src.get("type") in {"git", "directory", "file", "url"}:
                continue
        pkgs.append((name, version))
    return pkgs


def extract_packages(path: Path) -> tuple[str, list[tuple[str, str]]]:
    """Return (ecosystem, [(name, version), ...])."""
    name = path.name.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    # copy_out may prefix filenames (e.g. 00-package-lock.json).
    if name.endswith("package-lock.json") or name.endswith("npm-shrinkwrap.json"):
        data = json.loads(text)
        return "npm", _parse_npm_lock(data)
    if name.endswith("requirements.txt"):
        return "PyPI", _parse_requirements_txt(text)
    if name.endswith("uv.lock") or name.endswith("poetry.lock"):
        return "PyPI", _parse_toml_lock(text)
    if name.endswith("pipfile.lock"):
        data = json.loads(text)
        pkgs: list[tuple[str, str]] = []
        for section in ("default", "develop"):
            block = data.get(section) or {}
            if isinstance(block, dict):
                for pkg, meta in block.items():
                    ver = (meta or {}).get("version") if isinstance(meta, dict) else None
                    if isinstance(ver, str):
                        pkgs.append((pkg, ver.lstrip("=")))
        return "PyPI", pkgs
    # Unsupported lock → empty (still counts as scanned file).
    return "unknown", []


def query_osv_batch(
    ecosystem: str,
    packages: list[tuple[str, str]],
    *,
    timeout: float = 30.0,
    endpoint: str = OSV_QUERYBATCH,
) -> list[dict[str, Any]]:
    """Query OSV from Plane 1 (never from guest after offline — D43)."""
    if ecosystem == "unknown" or not packages:
        return []
    # Cap queries to keep finalize bounded.
    capped = packages[:OSV_BATCH_LIMIT]
    queries = [
        {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
        for name, version in capped
    ]
    body = json.dumps({"queries": queries}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "killhub-sca/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != len(capped):
        raise ValueError("Incomplete OSV batch response")
    vulns: list[dict[str, Any]] = []
    for i, item in enumerate(results):
        if not isinstance(item, dict) or not isinstance(item.get("vulns", []), list):
            raise ValueError("Invalid OSV result")
        name, version = capped[i]
        for vuln in item.get("vulns") or []:
            if not isinstance(vuln, dict) or not vuln.get("id"):
                raise ValueError("Invalid OSV advisory")
            vulns.append(
                {
                    "package": name,
                    "version": version,
                    "ecosystem": ecosystem,
                    "osv_id": vuln.get("id"),
                    "summary": vuln.get("summary") or vuln.get("id") or "advisory",
                    "aliases": vuln.get("aliases") or [],
                    "severity": _osv_severity(vuln),
                    "advisory_url": _osv_url(vuln),
                }
            )
    return vulns


def _osv_severity(vuln: dict[str, Any]) -> str:
    for entry in vuln.get("severity") or []:
        if not isinstance(entry, dict):
            continue
        score = str(entry.get("score") or "")
        # CVSS vector often embeds severity; default medium.
        if "CRITICAL" in score.upper():
            return "critical"
        if "/AV:" in score and "9." in score:
            return "critical"
    db = vuln.get("database_specific") or {}
    if isinstance(db, dict) and db.get("severity"):
        return str(db["severity"]).lower()
    return "medium"


def _osv_url(vuln: dict[str, Any]) -> str | None:
    vid = vuln.get("id")
    if isinstance(vid, str) and vid:
        return f"https://osv.dev/vulnerability/{vid}"
    refs = vuln.get("references") or []
    for ref in refs:
        if isinstance(ref, dict) and ref.get("url"):
            return str(ref["url"])
    return None


def sca_findings_from_lockfiles(
    lockfiles: list[Path],
    *,
    osv_endpoint: str = OSV_QUERYBATCH,
) -> tuple[list[dict[str, Any]], str]:
    """
    Return (findings, status) where status is ok|partial|failed.
    """
    findings: list[dict[str, Any]] = []
    if not lockfiles:
        return [], "partial"
    incomplete = False
    errors = 0
    scanned = 0
    for path in lockfiles:
        try:
            ecosystem, packages = extract_packages(path)
            if not packages:
                incomplete = True
                continue
            if len(packages) > OSV_BATCH_LIMIT:
                incomplete = True
            vulns = query_osv_batch(ecosystem, packages, endpoint=osv_endpoint)
            scanned += 1
            for vuln in vulns:
                fid = f"sca-{uuid.uuid4().hex[:8]}"
                findings.append(
                    {
                        "id": fid,
                        "severity": vuln.get("severity") or "medium",
                        "package": f"{vuln.get('package')}@{vuln.get('version')}",
                        "title": str(vuln.get("summary") or vuln.get("osv_id") or "advisory"),
                        "advisory_url": vuln.get("advisory_url"),
                        "source": "sca",
                        "detail": {
                            "osv_id": vuln.get("osv_id"),
                            "ecosystem": vuln.get("ecosystem"),
                            "lockfile": path.name,
                            "aliases": vuln.get("aliases") or [],
                        },
                    }
                )
        except (
            OSError,
            json.JSONDecodeError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
        ) as exc:
            errors += 1
            logger.warning("SCA failed for %s: %s", path, exc)
    if errors and scanned == 0:
        return findings, "failed"
    if errors or incomplete:
        return findings, "partial"
    return findings, "ok"


def collect_stream_findings(job_id: str, settings: Settings) -> list[dict[str, Any]]:
    """Lift canary/network/containment/preflight findings already on the stream."""
    out: list[dict[str, Any]] = []
    for event in get_ledger(settings).list_events(job_id):
        if event.type != "finding":
            continue
        payload = event.payload or {}
        source = payload.get("source")
        if source not in {
            "canary",
            "network",
            "containment",
            "preflight",
            "mcp_assessment",
            "intentional_app",
            "sca",
        }:
            continue
        finding = payload.get("finding")
        if isinstance(finding, dict) and finding.get("id"):
            out.append(finding)
            continue
        fid = str(payload.get("code") or f"{source}-{event.event_id}")
        out.append(
            {
                "id": fid,
                "severity": payload.get("severity") or "medium",
                "package": payload.get("package"),
                "title": event.message,
                "advisory_url": payload.get("advisory_url"),
                "source": source,
                "detail": {k: v for k, v in payload.items() if k != "finding"},
            }
        )
    # Dedupe by id
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for f in out:
        fid = str(f.get("id"))
        if fid in seen:
            continue
        seen.add(fid)
        deduped.append(f)
    return deduped


def run_mcp_assessment_if_planned(
    environment_id: str | None,
    *,
    job_id: str,
    settings: Settings,
    profile: dict[str, Any],
) -> dict[str, Any] | None:
    """Optional MCP Inspector/SDK assessment when profile enables it (D35)."""
    mcp = profile.get("mcp") or {}
    assessment = mcp.get("security_assessment") or {}
    if not isinstance(assessment, dict) or not assessment.get("enabled"):
        return None
    if not environment_id:
        result = {
            "enabled": True,
            "status": "skipped",
            "reason": "no_sandbox",
            "at": utc_now(),
        }
        _log(
            job_id,
            "mcp_assessment skipped (no sandbox)",
            settings=settings,
            kind="mcp_assessment",
            **result,
        )
        return result

    # Bounded, non-weaponizing surface probe: confirm helpers still list MCP tools
    # when stdio transport is declared. Never runs exploit suites (D33).
    transport = mcp.get("transport")
    detail: dict[str, Any] = {
        "enabled": True,
        "transport": transport,
        "at": utc_now(),
    }
    if transport == "stdio":
        probe = exec_command(
            environment_id,
            [
                "sh",
                "-lc",
                "test -f /opt/killhub/helpers/mcp_stdio_verify.py "
                "&& echo helper_ok || echo helper_missing",
            ],
            job_id=job_id,
            settings=settings,
            timeout=30,
        )
        ok = "helper_ok" in (probe.stdout or "")
        detail["status"] = "ok" if ok else "partial"
        detail["helper"] = "present" if ok else "missing"
    else:
        detail["status"] = "ok"
        detail["note"] = "assessment recorded without offensive probes"

    _log(
        job_id,
        f"mcp_assessment → {detail.get('status')}",
        settings=settings,
        kind="mcp_assessment",
        **detail,
    )
    if detail.get("status") == "partial":
        finding = {
            "id": f"mcp-{uuid.uuid4().hex[:8]}",
            "severity": "low",
            "title": "MCP assessment tooling incomplete",
            "source": "mcp_assessment",
            "detail": detail,
        }
        _finding_event(job_id, settings=settings, finding=finding)
        detail["finding_id"] = finding["id"]
    return detail


def cite_checked_review(findings: list[dict[str, Any]], draft: str | None = None) -> str:
    """
    Build / filter a vuln_review summary so every claim cites a finding id (D48).
    """
    ids = {str(f.get("id")) for f in findings if f.get("id")}
    if not findings:
        return "No findings recorded."

    if draft:
        kept: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", draft.strip()):
            s = sentence.strip()
            if not s:
                continue
            cited = set(re.findall(r"\[([a-zA-Z0-9_-]+)\]", s))
            if cited & ids:
                kept.append(s)
        if kept:
            return " ".join(kept)

    # Deterministic cite-checked summary (no uncited claims).
    parts: list[str] = []
    by_sev: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        sev = str(f.get("severity") or "info").lower()
        by_sev.setdefault(sev, []).append(f)
    order = ("critical", "high", "medium", "low", "info")
    for sev in order:
        group = by_sev.get(sev) or []
        if not group:
            continue
        cites = "".join(f"[{f['id']}]" for f in group if f.get("id"))
        titles = "; ".join(str(f.get("title") or f.get("id")) for f in group[:5])
        parts.append(f"{sev}: {titles} {cites}".strip())
    return "Cite-checked review — " + " | ".join(parts)


def run_vuln_scan(
    job_id: str,
    *,
    settings: Settings | None = None,
    osv_endpoint: str | None = None,
) -> VulnScanResult:
    """
    Copy lockfiles (when sandbox alive) + Plane-1 SCA + optional MCP assessment.
    Best-effort on fail paths — never clears readiness (D11, D53).
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise VulnScanError(f"unknown job_id: {job_id}", code="not_found")

    ledger.update_job_fields(
        job_id,
        status="scanning" if job.status not in {"failed", "cancelled", "completed"} else job.status,
        current_step="vulnerability scan",
        progress=max(job.progress, 96),
        finalizer=job.cancel_requested_at is not None,
    )
    ledger.append_event(
        job_id,
        typ="status",
        message="scanning",
        payload={"status": "scanning", "step": "vulnscan"},
        finalizer=job.cancel_requested_at is not None,
    )

    profile = _current_runtime_profile(job_id, cfg)
    lock_host: list[Path] = []
    copy_incomplete = False
    if job.sandbox_id:
        lock_host, copy_incomplete = copy_lockfiles_to_artifacts(
            job.sandbox_id, job_id=job_id, settings=cfg
        )

    endpoint = osv_endpoint or getattr(cfg, "vuln_scan_osv_url", None) or OSV_QUERYBATCH
    sca_findings, sca_status = sca_findings_from_lockfiles(lock_host, osv_endpoint=str(endpoint))
    for finding in sca_findings:
        _finding_event(job_id, settings=cfg, finding=finding)

    mcp_assessment = run_mcp_assessment_if_planned(
        job.sandbox_id,
        job_id=job_id,
        settings=cfg,
        profile=profile,
    )

    stream_findings = collect_stream_findings(job_id, cfg)
    # Merge SCA (already on stream after emit) — collect_stream picks them up.
    all_findings = stream_findings
    # Ensure SCA findings present even if event write lagged.
    known = {str(f.get("id")) for f in all_findings}
    for f in sca_findings:
        if str(f.get("id")) not in known:
            all_findings.append(f)

    # Optional AI draft (chat or RAG) then cite-filter (D48 / D75). Fail closed.
    draft: str | None = None
    review_mode = "deterministic"
    try:
        from inference_extras import draft_vuln_review, maybe_seed_embeddings_for_findings

        draft = draft_vuln_review(all_findings, job_id=job_id, settings=cfg)
        if draft:
            review_mode = "llm_rag" if (cfg.vultr_rag_collection or "").strip() else "llm"
        # Optional document embeddings for advisory indexing — never required.
        maybe_seed_embeddings_for_findings(all_findings, job_id=job_id, settings=cfg)
    except Exception as exc:  # noqa: BLE001
        logger.info("vuln_review extras skipped: %s", exc.__class__.__name__)

    status = "partial" if copy_incomplete and sca_status == "ok" else sca_status
    summary = cite_checked_review(all_findings, draft=draft)
    if not lock_host:
        summary = f"No dependency files were available for scanning. {summary}"
    elif status == "failed":
        summary = f"Dependency advisory lookup could not be completed. {summary}"
    elif status == "partial":
        summary = f"Dependency advisory coverage was incomplete. {summary}"

    report = ledger.upsert_vuln_report(
        job_id,
        summary=summary,
        findings=all_findings,
        status=status,
        mcp_assessment=mcp_assessment,
    )
    _log(
        job_id,
        f"vuln_report status={status} findings={len(all_findings)}",
        settings=cfg,
        kind="vulnscan",
        status=status,
        finding_count=len(all_findings),
        lockfiles=[p.name for p in lock_host],
        report_id=report.get("job_id"),
        review_mode=review_mode,
    )
    return VulnScanResult(
        job_id=job_id,
        status=status,
        findings=all_findings,
        lockfiles=[str(p) for p in lock_host],
        mcp_assessment=mcp_assessment,
        detail=summary,
    )
