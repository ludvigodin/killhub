"""Plane-1 pre-flight before bootstrap sandbox create (D45).

Cheap checks only — never run untrusted install on the control plane.
Hard-fail ⇒ terminal failed + findings; soft signals continue with findings.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from config import Settings, get_settings
from git_url import ALLOWED_GIT_HOSTS, parse_public_git_url
from jobs import get_ledger
from ledger.store import utc_now
from models import CleanupState

logger = logging.getLogger("killhub.preflight")


@dataclass(frozen=True)
class PreflightFinding:
    code: str
    message: str
    severity: str  # critical | high | medium | low | info
    hard: bool = False

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "source": "preflight",
            "code": self.code,
            "severity": self.severity,
            "hard": self.hard,
            "message": self.message,
        }


@dataclass
class PreflightResult:
    ok_to_bootstrap: bool
    findings: list[PreflightFinding] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def hard_findings(self) -> list[PreflightFinding]:
        return [f for f in self.findings if f.hard]

    @property
    def soft_findings(self) -> list[PreflightFinding]:
        return [f for f in self.findings if not f.hard]


def parse_github_owner_repo(github_url: str) -> tuple[str, str]:
    """Compatibility wrapper — parses any allowlisted public git URL (D78)."""
    parsed = parse_public_git_url(github_url)
    return parsed.owner, parsed.repo


def _deny_match(owner: str, repo: str, patterns: str) -> str | None:
    """Return matching deny pattern if owner/repo is blocked."""
    for raw in patterns.split(","):
        pat = raw.strip().lower()
        if not pat:
            continue
        if "/" not in pat:
            # org-only deny
            if owner.lower() == pat:
                return pat
            continue
        o, r = pat.split("/", 1)
        if owner.lower() != o:
            continue
        if r == "*" or r == repo.lower():
            return pat
    return None


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only while the target host stays on the git allowlist."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        host = (urlparse(newurl).hostname or "").lower()
        if host not in ALLOWED_GIT_HOSTS:
            raise urllib.error.HTTPError(
                newurl,
                code,
                f"redirect off allowlisted git host ({host or 'unknown'})",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _github_repo_meta(
    owner: str,
    repo: str,
    *,
    api_base: str,
    timeout: float,
    token: str = "",
) -> tuple[dict[str, Any] | None, PreflightFinding | None]:
    url = f"{api_base.rstrip('/')}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "killhub-preflight/0.1",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            if not isinstance(data, dict):
                return None, PreflightFinding(
                    code="github_meta_invalid",
                    message="GitHub metadata response was not an object",
                    severity="high",
                    hard=True,
                )
            return data, None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, PreflightFinding(
                code="repo_not_found",
                message=f"GitHub repository {owner}/{repo} not found or not public",
                severity="critical",
                hard=True,
            )
        if exc.code in {401, 403}:
            # Soft: API rate/auth — continue without inventing success or hard-fail
            return None, PreflightFinding(
                code="github_api_limited",
                message=f"GitHub metadata unavailable ({exc.code}); continuing without meta",
                severity="low",
                hard=False,
            )
        return None, PreflightFinding(
            code="github_api_error",
            message=f"GitHub metadata HTTP {exc.code}",
            severity="medium",
            hard=False,
        )
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, PreflightFinding(
            code="github_api_unreachable",
            message=f"GitHub metadata unreachable: {exc.__class__.__name__}",
            severity="low",
            hard=False,
        )


def _host_reachability(
    page_url: str,
    *,
    timeout: float,
) -> PreflightFinding | None:
    """Cheap HTTPS reachability for non-GitHub allowlisted hosts (D78)."""
    headers = {"User-Agent": "killhub-preflight/0.1"}
    opener = urllib.request.build_opener(_AllowlistedRedirectHandler())
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(page_url, headers=headers, method=method)
        try:
            with opener.open(req, timeout=timeout) as resp:
                code = getattr(resp, "status", None) or resp.getcode()
                if int(code) == 404:
                    return PreflightFinding(
                        code="repo_not_found",
                        message=f"repository page not found at {page_url}",
                        severity="critical",
                        hard=True,
                    )
                return None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return PreflightFinding(
                    code="repo_not_found",
                    message=f"repository page not found at {page_url}",
                    severity="critical",
                    hard=True,
                )
            if exc.code in {401, 403}:
                return PreflightFinding(
                    code="host_meta_limited",
                    message=(
                        f"repository metadata unavailable ({exc.code}); continuing without meta"
                    ),
                    severity="low",
                    hard=False,
                )
            if exc.code in {301, 302, 303, 307, 308}:
                # Redirect handler already blocked off-host; treat as soft.
                return PreflightFinding(
                    code="host_redirect_blocked",
                    message=(
                        "repository redirected off allowlisted git host; continuing without meta"
                    ),
                    severity="low",
                    hard=False,
                )
            if method == "HEAD" and exc.code in {405, 501}:
                continue
            return PreflightFinding(
                code="host_meta_error",
                message=f"repository reachability HTTP {exc.code}",
                severity="medium",
                hard=False,
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            return PreflightFinding(
                code="host_unreachable",
                message=f"repository host unreachable: {exc.__class__.__name__}",
                severity="low",
                hard=False,
            )
    return PreflightFinding(
        code="host_unreachable",
        message="repository host unreachable after HEAD/GET",
        severity="low",
        hard=False,
    )


def run_preflight(
    github_url: str,
    *,
    settings: Settings | None = None,
) -> PreflightResult:
    """Execute cheap Plane-1 checks. Does not create a sandbox."""
    cfg = settings or get_settings()
    findings: list[PreflightFinding] = []
    meta: dict[str, Any] = {"github_url": github_url}

    if not getattr(cfg, "preflight_enabled", True):
        return PreflightResult(ok_to_bootstrap=True, findings=[], meta={"skipped": True})

    try:
        parsed = parse_public_git_url(github_url)
    except ValueError as exc:
        findings.append(
            PreflightFinding(
                code="invalid_url",
                message=str(exc),
                severity="critical",
                hard=True,
            )
        )
        return PreflightResult(ok_to_bootstrap=False, findings=findings, meta=meta)

    owner, repo = parsed.owner, parsed.repo
    meta["owner"] = owner
    meta["repo"] = repo
    meta["host"] = parsed.host
    meta["canonical_url"] = parsed.url

    deny = _deny_match(owner, repo, getattr(cfg, "preflight_deny_repos", "") or "")
    if deny:
        findings.append(
            PreflightFinding(
                code="deny_list",
                message=f"repository matched preflight deny list ({deny})",
                severity="critical",
                hard=True,
            )
        )
        # No need to burn GitHub API / VX1 — deny is already decisive.
        return PreflightResult(
            ok_to_bootstrap=False,
            findings=findings,
            meta=meta,
        )

    # Suspicious path tokens — soft unless deny hit.
    lowered = f"{owner}/{repo}".lower()
    for token in ("malware", "ransomware", "c2-framework", "botnet"):
        if token in lowered:
            findings.append(
                PreflightFinding(
                    code="suspicious_name",
                    message=f"repository name contains hostile token '{token}'",
                    severity="medium",
                    hard=False,
                )
            )

    timeout = float(getattr(cfg, "preflight_timeout_seconds", 5) or 5)

    if parsed.host == "github.com":
        api_base = getattr(cfg, "preflight_github_api", None) or "https://api.github.com"
        token = (getattr(cfg, "github_token", None) or "").strip()
        data, meta_finding = _github_repo_meta(
            owner, repo, api_base=api_base, timeout=timeout, token=token
        )
        if meta_finding is not None:
            findings.append(meta_finding)

        if data is not None:
            meta["github"] = {
                "private": bool(data.get("private")),
                "archived": bool(data.get("archived")),
                "disabled": bool(data.get("disabled")),
                "fork": bool(data.get("fork")),
                "size": data.get("size"),
                "default_branch": data.get("default_branch"),
                "visibility": data.get("visibility"),
            }
            if data.get("private") or data.get("visibility") == "private":
                findings.append(
                    PreflightFinding(
                        code="repo_private",
                        message="repository is private; Killhub v1 accepts public repos only",
                        severity="critical",
                        hard=True,
                    )
                )
            if data.get("disabled"):
                findings.append(
                    PreflightFinding(
                        code="repo_disabled",
                        message="repository is disabled on GitHub",
                        severity="critical",
                        hard=True,
                    )
                )
            if data.get("archived"):
                findings.append(
                    PreflightFinding(
                        code="repo_archived",
                        message="repository is archived; continuing with caution",
                        severity="low",
                        hard=False,
                    )
                )
            size_kb = int(data.get("size") or 0)
            max_soft = int(getattr(cfg, "preflight_soft_max_size_kb", 500_000) or 500_000)
            if size_kb > max_soft:
                findings.append(
                    PreflightFinding(
                        code="repo_large",
                        message=f"repository size {size_kb}KB exceeds soft threshold {max_soft}KB",
                        severity="low",
                        hard=False,
                    )
                )
            if not data.get("default_branch"):
                findings.append(
                    PreflightFinding(
                        code="repo_empty",
                        message="repository has no default branch (empty?)",
                        severity="high",
                        hard=True,
                    )
                )
    else:
        reach = _host_reachability(parsed.url, timeout=timeout)
        if reach is not None:
            findings.append(reach)

    hard = [f for f in findings if f.hard]
    return PreflightResult(
        ok_to_bootstrap=len(hard) == 0,
        findings=findings,
        meta=meta,
    )


def apply_preflight_to_job(
    job_id: str,
    result: PreflightResult,
    *,
    settings: Settings | None = None,
) -> None:
    """Persist preflight log/finding events; hard-fail marks terminal failed (no msb)."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)

    ledger.append_event(
        job_id,
        typ="log",
        message="preflight completed" if result.ok_to_bootstrap else "preflight hard-fail",
        payload={
            "kind": "preflight",
            "ok_to_bootstrap": result.ok_to_bootstrap,
            "finding_count": len(result.findings),
            "hard_count": len(result.hard_findings),
            "meta": {
                k: v for k, v in result.meta.items() if k in {"owner", "repo", "host", "skipped"}
            },
        },
    )

    for finding in result.findings:
        ledger.append_event(
            job_id,
            typ="finding",
            message=finding.message,
            payload=finding.to_event_payload(),
        )

    if result.ok_to_bootstrap:
        return

    now = utc_now()
    hard_msgs = "; ".join(f.message for f in result.hard_findings)[:500]
    # Receipt, status event and terminal status in one transaction (D61).
    ledger.finalize_job(
        job_id,
        status="failed",
        receipt={
            "verification": {"kind": "preflight_failed"},
            "containment": {"status": "skipped", "reason": "preflight_hard_fail"},
            "lifecycle": {"preflight": False, "sandbox_created": False},
            "dossier": {
                "outcome": "failed",
                "reason": "preflight_hard_fail",
                "findings": [f.to_event_payload() for f in result.findings],
            },
        },
        event_message="failed",
        event_payload={"reason": "preflight"},
        progress=100,
        current_step="preflight hard-fail",
        error=hard_msgs or "preflight hard-fail",
        cleanup=CleanupState(status="destroyed", attempts=0, updated_at=now),
        destroyed_at=now,
    )
