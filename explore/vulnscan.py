"""Plane-1 SCA against copied lockfiles + optional MCP assessment (D33, D43, D35)."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from active_report import ACTIVE_SOURCES, active_finding, with_active_summary
from config import Settings, get_settings
from errors import HarnessError
from fixtures import match_fixture
from harness import copy_out, exec_command
from jobs import get_ledger
from ledger.store import FINDING_SOURCES, utc_now
from models import JobEvent
from safety import review_priority

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
OSV_MAX_BATCHES = 16
OSV_LOOKUP_SECONDS = 30
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
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        import tomli as tomllib  # type: ignore[no-redef]

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
    if len(packages) > OSV_BATCH_LIMIT:
        raise ValueError("OSV request exceeds batch size")
    queries = [
        {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
        for name, version in packages
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
    if not isinstance(results, list) or len(results) != len(packages):
        raise ValueError("Incomplete OSV batch response")
    vulns: list[dict[str, Any]] = []
    for i, item in enumerate(results):
        if not isinstance(item, dict) or not isinstance(item.get("vulns", []), list):
            raise ValueError("Invalid OSV result")
        name, version = packages[i]
        for vuln in item.get("vulns") or []:
            if not isinstance(vuln, dict) or not vuln.get("id"):
                raise ValueError("Invalid OSV advisory")
            # Batch payloads are ID/modified only; severity stays unknown until enrich.
            vulns.append(
                {
                    "package": name,
                    "version": version,
                    "ecosystem": ecosystem,
                    "osv_id": vuln.get("id"),
                    "summary": vuln.get("summary") or vuln.get("id") or "advisory",
                    "aliases": vuln.get("aliases") or [],
                    "severity": _osv_severity(vuln) if vuln.get("severity") else "unknown",
                    "advisory_url": _osv_url(vuln),
                }
            )
    return vulns


_SEVERITY_LABELS = frozenset({"critical", "high", "medium", "moderate", "low", "info"})


def _cvss_band(score: float) -> str:
    # CVSS v3/v4 qualitative severity bands.
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "medium"
    if score >= 0.0:
        return "low"
    return "unknown"


def _cvss_base_from_vector(vector: str) -> float | None:
    """Compute CVSS v3.x base score from a vector string, or None if unsupported."""
    raw = vector.strip()
    if not raw.upper().startswith("CVSS:3"):
        return None
    parts = raw.split("/")
    if len(parts) < 2:
        return None
    metrics: dict[str, str] = {}
    for part in parts[1:]:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        metrics[key.upper()] = value.upper()
    required = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")
    if any(k not in metrics for k in required):
        return None

    av = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.2}.get(metrics["AV"])
    ac = {"L": 0.77, "H": 0.44}.get(metrics["AC"])
    scope_changed = metrics["S"] == "C"
    pr = (
        {"N": 0.85, "L": 0.68, "H": 0.5} if scope_changed else {"N": 0.85, "L": 0.62, "H": 0.27}
    ).get(metrics["PR"])
    ui = {"N": 0.85, "R": 0.62}.get(metrics["UI"])
    cia = {"H": 0.56, "L": 0.22, "N": 0.0}
    c_score = cia.get(metrics["C"])
    i_score = cia.get(metrics["I"])
    a_score = cia.get(metrics["A"])
    if None in (av, ac, pr, ui, c_score, i_score, a_score):
        return None

    exploitability = 8.22 * av * ac * pr * ui  # type: ignore[operator]
    impact_sub = 1 - ((1 - c_score) * (1 - i_score) * (1 - a_score))  # type: ignore[operator]
    if scope_changed:
        impact = 7.52 * (impact_sub - 0.029) - 3.25 * (impact_sub - 0.02) ** 15
        if impact <= 0:
            return 0.0
        base = min(1.08 * (impact + exploitability), 10.0)
    else:
        impact = 6.42 * impact_sub
        if impact <= 0:
            return 0.0
        base = min(impact + exploitability, 10.0)
    # Round up to 1 decimal (CVSS rounding).
    return float(int(base * 10 + 0.999999) / 10)


def _normalize_severity_label(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    label = raw.strip().lower()
    if label == "moderate":
        return "medium"
    if label in _SEVERITY_LABELS:
        return label
    return None


def _severity_from_score_field(score: Any) -> str | None:
    if isinstance(score, (int, float)):
        return _cvss_band(float(score))
    if not isinstance(score, str):
        return None
    text = score.strip()
    if not text:
        return None
    labeled = _normalize_severity_label(text)
    if labeled:
        return labeled
    # Bare numeric score.
    try:
        return _cvss_band(float(text))
    except ValueError:
        pass
    # CVSS vector string.
    if "CVSS:" in text.upper() or "/AV:" in text.upper():
        base = _cvss_base_from_vector(text)
        if base is not None:
            return _cvss_band(base)
        upper = text.upper()
        if "CRITICAL" in upper:
            return "critical"
        if "HIGH" in upper:
            return "high"
        if "MEDIUM" in upper or "MODERATE" in upper:
            return "medium"
        if "LOW" in upper:
            return "low"
    return None


def _osv_severity(vuln: dict[str, Any]) -> str:
    """Resolve severity from a full OSV record. Never invent medium."""
    for entry in vuln.get("severity") or []:
        if not isinstance(entry, dict):
            continue
        band = _severity_from_score_field(entry.get("score"))
        if band:
            return band
    db = vuln.get("database_specific") or {}
    if isinstance(db, dict):
        labeled = _normalize_severity_label(db.get("severity"))
        if labeled:
            return labeled
    for affected in vuln.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        eco = affected.get("ecosystem_specific") or {}
        if isinstance(eco, dict):
            labeled = _normalize_severity_label(eco.get("severity"))
            if labeled:
                return labeled
    return "unknown"


def _osv_url(vuln: dict[str, Any]) -> str | None:
    vid = vuln.get("id")
    if isinstance(vid, str) and vid:
        return f"https://osv.dev/vulnerability/{vid}"
    refs = vuln.get("references") or []
    for ref in refs:
        if isinstance(ref, dict) and ref.get("url"):
            return str(ref["url"])
    return None


def _advisory_id_only(finding: dict[str, Any]) -> bool:
    detail = finding.get("detail") or {}
    return finding.get("source") == "sca" and (
        not finding.get("title")
        or finding["title"] == detail.get("osv_id")
        or re.fullmatch(r"(?:GHSA|PYSEC|CVE|OSV|RUSTSEC)-[A-Za-z0-9-]+", finding["title"])
        is not None
    )


def _fetch_osv_vuln(advisory_id: str, *, timeout: float) -> dict[str, Any] | None:
    if (
        not isinstance(advisory_id, str)
        or timeout <= 0
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", advisory_id)
    ):
        return None
    try:
        url = f"https://api.osv.dev/v1/vulns/{advisory_id}"
        with urllib.request.urlopen(url, timeout=min(timeout, 3.0)) as response:
            data = json.loads(response.read(256_000))
        if isinstance(data, dict) and data.get("id") == advisory_id:
            return data
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return None


def _enrich_sca_findings(
    findings: list[dict[str, Any]],
    *,
    deadline: float,
) -> bool:
    """Fetch full OSV records for unique IDs. Returns True if enrichment incomplete."""
    cache: dict[str, dict[str, Any] | None] = {}
    incomplete = False
    for finding in findings:
        detail = finding.get("detail") if isinstance(finding.get("detail"), dict) else {}
        advisory_id = detail.get("osv_id")
        if not isinstance(advisory_id, str) or not advisory_id:
            continue
        # Skip findings that already carry a known severity (tests / non-batch sources).
        current = str(finding.get("severity") or "unknown").lower()
        needs_score = current in {"", "unknown"}
        needs_title = _advisory_id_only(finding)
        if not needs_score and not needs_title:
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            incomplete = True
            break
        if advisory_id not in cache:
            cache[advisory_id] = _fetch_osv_vuln(advisory_id, timeout=remaining)
        record = cache[advisory_id]
        if record is None:
            if needs_score:
                incomplete = True
            # Keep provisional unknown; IDs already retained.
            continue
        if needs_score:
            finding["severity"] = _osv_severity(record)
        aliases = record.get("aliases") or []
        if isinstance(aliases, list):
            detail["aliases"] = [a for a in aliases if isinstance(a, str)]
        description = record.get("summary") or record.get("details")
        if isinstance(description, str) and description.strip():
            finding["title"] = " ".join(description.split())[:500]
        finding["advisory_url"] = finding.get("advisory_url") or _osv_url(record)
        finding["detail"] = detail
    return incomplete


def sca_findings_from_lockfiles(
    lockfiles: list[Path],
    *,
    osv_endpoint: str = OSV_QUERYBATCH,
) -> tuple[list[dict[str, Any]], str, int, int]:
    """
    Return findings, status, checked entries and discovered pinned entries.
    """
    findings: list[dict[str, Any]] = []
    incomplete = not lockfiles
    deadline = time.monotonic() + OSV_LOOKUP_SECONDS
    requested = 0
    discovered = 0
    errors = 0
    scanned = 0
    for path in lockfiles:
        try:
            ecosystem, packages = extract_packages(path)
            if not packages:
                incomplete = True
                continue
            discovered += len(packages)
            for start in range(0, len(packages), OSV_BATCH_LIMIT):
                remaining = deadline - time.monotonic()
                if requested >= OSV_MAX_BATCHES or remaining <= 0:
                    incomplete = True
                    break
                batch = packages[start : start + OSV_BATCH_LIMIT]
                requested += 1
                vulns = query_osv_batch(ecosystem, batch, endpoint=osv_endpoint, timeout=remaining)
                scanned += len(batch)
                for vuln in vulns:
                    fid = f"sca-{uuid.uuid4().hex[:8]}"
                    # querybatch is ID-only; provisional unknown until enrichment.
                    findings.append(
                        {
                            "id": fid,
                            "severity": vuln.get("severity") or "unknown",
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
    enrichment_incomplete = False
    if findings and osv_endpoint == OSV_QUERYBATCH:
        enrichment_incomplete = _enrich_sca_findings(findings, deadline=deadline)
    if errors and scanned == 0:
        return findings, "failed", scanned, discovered
    if errors or incomplete or enrichment_incomplete:
        return findings, "partial", scanned, discovered
    return findings, "ok", scanned, discovered


def collect_stream_findings(job_id: str, settings: Settings) -> list[dict[str, Any]]:
    """Lift canary/network/containment/preflight findings already on the stream."""
    out: list[dict[str, Any]] = []
    for event in get_ledger(settings).list_events(job_id):
        if event.type != "finding":
            continue
        payload = event.payload or {}
        source = payload.get("source")
        if source not in FINDING_SOURCES:
            continue
        if source in ACTIVE_SOURCES:
            out.append(active_finding(event))
            continue
        finding = payload.get("finding")
        if isinstance(finding, dict) and finding.get("id"):
            out.append(finding)
            continue
        fid = str(payload.get("code") or f"{source}-{event.event_id}")
        out.append(
            {
                "id": fid,
                "severity": payload.get("severity") or "unknown",
                "package": payload.get("package"),
                "title": event.message,
                "advisory_url": payload.get("advisory_url"),
                "source": source,
                "detail": {k: v for k, v in payload.items() if k not in {"finding", "excerpt"}},
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


def _measure_filesystem_read(
    environment_id: str, job_id: str, settings: Settings
) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    try:
        result = exec_command(
            environment_id,
            ["python3", "-E", "-s", "/opt/killhub/helpers/mcp_fixture_read.py"],
            job_id=job_id,
            settings=settings,
            timeout=20,
        )
        measurement = json.loads(result.stdout) if result.exit_code == 0 else {}
        if not isinstance(measurement, dict):
            measurement = {}
        status = measurement.get("status")
        if (
            status in ("passed", "failed")
            and all(
                isinstance(measurement.get(k), str)
                and re.fullmatch(r"[0-9a-f]{64}", measurement[k])
                for k in ("expected_sha256", "response_sha256", "schema_sha256")
            )
            and type(measurement.get("elapsed_ms")) is int
            and measurement["elapsed_ms"] >= 0
            and type(measurement.get("fixture_unchanged")) is bool
            and measurement.get("tool") == "read_text_file"
        ):
            for key in (
                "tool",
                "expected_sha256",
                "response_sha256",
                "schema_sha256",
                "fixture_unchanged",
                "elapsed_ms",
            ):
                detail[key] = measurement[key]
            detail["timeout_ms"] = 15000
            matched = (
                detail["fixture_unchanged"]
                and detail["response_sha256"] == detail["expected_sha256"]
                and detail["elapsed_ms"] <= detail["timeout_ms"]
            )
            detail["status"] = "passed" if matched and status == "passed" else "failed"
        else:
            detail.update(status="partial", reason="measurement_unavailable")
    except (HarnessError, ValueError):
        detail.update(status="partial", reason="measurement_unavailable")
    return detail


def _has_offline_evidence(events: list[JobEvent], environment_id: str) -> bool:
    restored = False
    denied = False
    for event in events:
        payload = event.payload
        if event.type == "lifecycle" and payload.get("phase") == "network_verify":
            restored = (
                payload.get("environment_id") == environment_id
                and (payload.get("net") or {}).get("no_net") is True
            )
            denied = False
        elif (
            event.type == "log" and payload.get("kind") == "install" and "offline_probe" in payload
        ):
            denied = (payload.get("offline_probe") or {}).get("classification") == "policy_denied"
    return restored and denied


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
    ledger = get_ledger(settings)
    job = ledger.get_job(job_id)
    fixture = match_fixture(job.github_url) if job else None
    transport = mcp.get("transport")
    detail = {
        "enabled": True,
        "check": "filesystem_read_v1",
        "transport": transport,
        "at": utc_now(),
        "status": "skipped",
    }
    if not environment_id or not job or job.sandbox_id != environment_id:
        detail["reason"] = "no_current_sandbox"
    elif transport != "stdio" or assessment.get("check") != detail["check"]:
        detail["reason"] = "no_supported_behavior_check"
    elif (
        not fixture
        or fixture["id"] != "git_mcp_filesystem"
        or job.resolved_commit != fixture["commit"]
        or (profile.get("source") or {}).get("commit") != fixture["commit"]
    ):
        detail["reason"] = "unmatched_fixture_revision"
    elif (
        job.cancel_requested_at
        or not (job.readiness or {}).get("passed")
        or (job.verification or {}).get("kind") != "original_application"
    ):
        detail["reason"] = "original_readiness_required"
    elif not _has_offline_evidence(ledger.list_events(job_id), environment_id):
        detail["reason"] = "offline_evidence_missing"
    else:
        detail["resolved_commit"] = job.resolved_commit
        detail.update(_measure_filesystem_read(environment_id, job_id, settings))
    _log(
        job_id,
        f"mcp_assessment → {detail.get('status')}",
        settings=settings,
        kind="mcp_assessment",
        **detail,
    )
    if detail.get("status") in ("failed", "partial"):
        finding = {
            "id": f"mcp-{uuid.uuid4().hex[:8]}",
            "severity": "low",
            "title": "Fixture read differed from expected behavior"
            if detail["status"] == "failed"
            else "Fixture read evidence incomplete",
            "source": "mcp_assessment",
            "detail": detail,
        }
        _finding_event(job_id, settings=settings, finding=finding)
        detail["finding_id"] = finding["id"]
    return detail


def _checked_draft(findings: list[dict[str, Any]], draft: str) -> str | None:
    priorities = {str(f["id"]): review_priority(f) for f in findings if f.get("id")}
    if not priorities:
        return None
    highest = min(priorities.values())
    kept: list[str] = []
    mentions_highest = False
    for sentence in re.split(r"(?<=[.!?])\s+", draft.strip()):
        cited = set(re.findall(r"\[([^]\n]+)\]", sentence))
        if cited and cited <= priorities.keys():
            kept.append(sentence)
            mentions_highest |= any(priorities[i] == highest for i in cited)
    summary = " ".join(kept)
    if mentions_highest and len(kept) <= 2 and len(summary.split()) <= 60:
        return summary
    return None


def cite_checked_review(findings: list[dict[str, Any]], draft: str | None = None) -> str:
    """Build a short review grounded in identified findings (D48)."""
    if not findings:
        return "No findings recorded."
    findings = [f for f in findings if f.get("id")]
    if not findings:
        return "The scan recorded findings without identifiers. Review the details below."
    finding = min(findings, key=review_priority)
    citation = f"[{finding['id']}]"
    if _advisory_id_only(finding):
        package = finding.get("package") or "a project dependency"
        return (
            f"A security advisory lists {package} as affected {citation}. "
            "The scan did not establish how this affects the application. "
            "Check the advisory for a fixed version before running the project."
        )
    if review_priority(finding) == 5:
        if (
            finding.get("source") == "network"
            and (finding.get("detail") or {}).get("classification") == "policy_denied"
        ):
            return f"The sandbox blocked a network connection as expected {citation}."
        return f"The scan recorded an informational observation {citation}."
    if draft and (summary := _checked_draft(findings, draft)):
        return summary
    title = " ".join(str(finding.get("title") or "Issue flagged").split())
    if len(title) > 140:
        title = title[:137].rstrip() + "…"
    if finding.get("source") == "sca" and finding.get("package"):
        return (
            f"A published security warning applies to {finding['package']}: {title} {citation}. "
            "Check the advisory for a fixed version before running the project."
        )
    return f"The scan flagged the following issue: {title} {citation}."


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
    sca_findings, sca_status, checked, discovered = sca_findings_from_lockfiles(
        lock_host, osv_endpoint=str(endpoint)
    )
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

    # Keep metadata service warnings in the detailed report, outside the security review.
    review_findings = [
        f
        for f in all_findings
        if not (f.get("source") == "preflight" and f.get("id") == "github_api_limited")
    ]
    # Optional AI draft (chat or RAG) then cite-filter (D48 / D75). Fail closed.
    draft: str | None = None
    review_mode = "deterministic"
    try:
        from inference_extras import draft_vuln_review, maybe_seed_embeddings_for_findings

        ranked = sorted(review_findings, key=review_priority)
        if ranked and review_priority(ranked[0]) != 5 and not _advisory_id_only(ranked[0]):
            draft = draft_vuln_review([ranked[0]], job_id=job_id, settings=cfg)
        if draft := _checked_draft(ranked[:1], draft or ""):
            review_mode = "llm_rag" if (cfg.vultr_rag_collection or "").strip() else "llm"
        # Optional document embeddings for advisory indexing — never required.
        maybe_seed_embeddings_for_findings(all_findings, job_id=job_id, settings=cfg)
    except Exception as exc:  # noqa: BLE001
        logger.info("vuln_review extras skipped: %s", exc.__class__.__name__)

    status = "partial" if copy_incomplete and sca_status == "ok" else sca_status
    summary = with_active_summary(
        draft or (cite_checked_review(review_findings) if review_findings else ""), all_findings
    )
    if not lock_host:
        summary = f"{summary} No dependency files were available for scanning."
    elif status == "failed":
        summary = f"{summary} The lookup for known dependency issues failed."
    elif status == "partial":
        summary = f"{summary} Some dependencies could not be checked for known security issues."

    if discovered:
        coverage = f"Checked {checked} of {discovered} listed dependency versions."
        if checked and not sca_findings:
            coverage += " No known advisories were returned for the checked versions."
        if any(review_priority(f) < 5 for f in review_findings):
            summary = f"{summary} {coverage}"
        else:
            summary = f"{coverage} {summary}"

    summary = summary.strip()
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
        packages_checked=checked,
        packages_discovered=discovered,
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
