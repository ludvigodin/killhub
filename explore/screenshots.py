"""Optional in-guest Playwright stills (E4, D18, D31, D38).

Never gates readiness or completion. Never runs untrusted page JS on Plane 1.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from harness import copy_out, exec_command
from jobs import get_ledger
from ledger.store import utc_now
from object_storage import cdn_url_for_s3_ref, is_s3_ref, maybe_upload_local_file

logger = logging.getLogger("killhub.screenshots")

GUEST_HELPERS = "/opt/killhub/helpers"
GUEST_TOOLING = "/opt/killhub/tooling"
GUEST_SHOT_DIR = "/tmp/killhub/screenshots"

# Caption redaction — never persist secret-shaped tokens (D17 / D44).
_SECRETISH = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*\S+")
_CANARYISH = re.compile(r"CKEY_[0-9a-fA-F]{20,}|KILLHUB_CANARY_[A-Z0-9_]+")


@dataclass
class ScreenshotResult:
    job_id: str
    status: str  # captured | skipped | failed
    reason: str = ""
    screenshots: list[dict[str, Any]] = field(default_factory=list)


class ScreenshotError(Exception):
    def __init__(self, message: str, *, code: str = "screenshot_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def redact_caption(text: str) -> str:
    cleaned = _SECRETISH.sub(r"\1=[redacted]", text or "")
    cleaned = _CANARYISH.sub("[redacted]", cleaned)
    return cleaned[:240]


def _log(job_id: str, message: str, *, settings: Settings, kind: str, **payload: Any) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": kind, **payload},
    )


def _api_screenshot_url(job_id: str, screenshot_id: str) -> str:
    return f"/api/jobs/{job_id}/screenshots/{screenshot_id}"


def public_screenshot_url(
    job_id: str,
    screenshot_id: str,
    *,
    storage_path: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Prefer CDN absolute URL when s3 + OBJECT_STORAGE_CDN_BASE_URL (D76)."""
    if storage_path:
        cdn = cdn_url_for_s3_ref(storage_path, settings=settings)
        if cdn:
            return cdn
    return _api_screenshot_url(job_id, screenshot_id)


def _current_runtime_profile(job_id: str, settings: Settings) -> dict[str, Any]:
    ledger = get_ledger(settings)
    revs = ledger.list_profile_revisions(job_id)
    runtime = [r for r in revs if r.phase == "runtime"]
    if runtime:
        return dict(runtime[-1].profile or {})
    job = ledger.get_job(job_id)
    if job and job.environment_profile:
        return dict(job.environment_profile)
    return {}


def _select_http_url(profile: dict[str, Any], readiness: dict[str, Any] | None) -> str | None:
    """Pick a loopback HTTP URL from probes / readiness detail."""
    probes = profile.get("probes") or profile.get("healthcheck") or []
    if isinstance(probes, dict):
        probes = [probes]
    for p in probes:
        if not isinstance(p, dict):
            continue
        url = str(p.get("url") or "").strip()
        if url.startswith(("http://127.0.0.1", "http://localhost")):
            return url
    ports = [int(p) for p in (profile.get("ports") or []) if str(p).isdigit()]
    if ports:
        return f"http://127.0.0.1:{ports[0]}/"
    detail = (readiness or {}).get("detail") or {}
    for item in detail.get("probes") or []:
        if isinstance(item, dict):
            url = str(item.get("url") or item.get("probe") or "").strip()
            if url.startswith(("http://127.0.0.1", "http://localhost")):
                return url
    return None


def should_capture_screenshots(
    job_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[bool, str]:
    """D31: only when useful (HTTP webapp/demo verify). Skip MCP CLI / early fail."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        return False, "not_found"
    if job.status in {"cancelled"}:
        return False, "cancelled"
    if not job.sandbox_id:
        return False, "no_sandbox"
    readiness = job.readiness or {}
    if not readiness.get("passed"):
        return False, "readiness_not_passed"
    verification = job.verification or {}
    if verification.get("kind") == "setup_failed":
        return False, "setup_failed"
    profile = _current_runtime_profile(job_id, cfg)
    intent = profile.get("intent")
    if intent == "git_mcp":
        mcp = profile.get("mcp") or {}
        if mcp.get("transport") != "streamable_http":
            return False, "cli_only_mcp"
    if intent not in {"webapp", "demo"} and intent != "git_mcp":
        # Unknown / missing intent — only capture when we have an HTTP probe URL.
        if _select_http_url(profile, readiness) is None:
            return False, "no_http_target"
    elif intent == "git_mcp":
        # streamable_http MCP may still benefit from a still of the HTTP surface.
        if _select_http_url(profile, readiness) is None:
            return False, "mcp_http_no_url"
    url = _select_http_url(profile, readiness)
    if not url:
        return False, "no_http_target"
    existing = ledger.list_screenshots(job_id)
    if len(existing) >= max(int(cfg.max_screenshots_per_job), 0):
        return False, "screenshot_cap"
    total = 0
    for shot in existing:
        ref = str(shot.get("storage_path") or "")
        # Disk budget is host-local (D40); s3-only refs do not consume local disk.
        if is_s3_ref(ref):
            continue
        path = Path(ref)
        if path.is_file():
            total += path.stat().st_size
    budget = max(int(cfg.max_screenshots_per_job), 1) * max(int(cfg.max_copy_bytes), 1)
    # Soft disk budget: refuse when retained stills already consume the budget.
    if total >= budget:
        return False, "screenshot_disk_budget"
    return True, "ok"


def ensure_playwright_tooling(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
    intent: str | None = None,
) -> dict[str, Any]:
    """
    Best-effort Playwright + Chromium install during install-phase egress (D63).

    Skipped for CLI-only MCP. Failure is logged — never invents capture success.
    """
    if intent == "git_mcp":
        # streamable_http may still want tooling; callers pass intent from profile.
        # Default: install for webapp/demo only unless explicitly requested.
        pass
    if intent not in {None, "webapp", "demo", "git_mcp"}:
        return {"status": "skipped", "reason": "intent_not_http"}

    browsers = f"{GUEST_TOOLING}/playwright/browsers"
    site = f"{GUEST_TOOLING}/playwright/py"
    script = (
        "export DEBIAN_FRONTEND=noninteractive; "
        f"mkdir -p {GUEST_TOOLING}/playwright {browsers} {site}; "
        # System Chromium avoids a full Playwright browser download when available.
        "if command -v apt-get >/dev/null 2>&1; then "
        "apt-get update -qq && "
        "apt-get install -y -qq python3-pip python3-venv "
        "chromium chromium-common fonts-liberation "
        "libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 "
        "libasound2t64 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 "
        "2>/dev/null || "
        "apt-get install -y -qq python3-pip python3-venv "
        "chromium fonts-liberation "
        "libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 libgbm1 "
        "libasound2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 "
        "2>/dev/null || "
        "apt-get install -y -qq python3-pip || true; "
        "fi; "
        "python3 -m ensurepip --default-pip >/dev/null 2>&1 || true; "
        f"(python3 -m pip install --upgrade --target {site} 'playwright>=1.40' || "
        f"pip3 install --upgrade --target {site} 'playwright>=1.40') || exit 4; "
        f"export PYTHONPATH={site}${{PYTHONPATH:+:$PYTHONPATH}}; "
        f"export PLAYWRIGHT_BROWSERS_PATH={browsers}; "
        # Prefer system chromium; fall back to Playwright-managed browser.
        "if command -v chromium >/dev/null 2>&1 || "
        "command -v chromium-browser >/dev/null 2>&1; then "
        "echo chromium_system; exit 0; fi; "
        "python3 -m playwright install chromium || exit 5; "
        "echo chromium_playwright; exit 0"
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", script],
        job_id=job_id,
        settings=settings,
        timeout=600,
    )
    status = "ok" if result.exit_code == 0 else "failed"
    meta = {
        "status": status,
        "exit_code": result.exit_code,
        "detail": ((result.stdout or "") + (result.stderr or ""))[-500:],
        "browsers_path": browsers,
        "pythonpath": site,
    }
    _log(
        job_id,
        f"playwright tooling → {status}",
        settings=settings,
        kind="screenshot_tooling",
        **meta,
    )
    return meta


def capture_http_screenshot(
    job_id: str,
    *,
    settings: Settings | None = None,
    url: str | None = None,
    step: str = "verify",
    caption: str | None = None,
) -> ScreenshotResult:
    """
    Run Playwright inside Plane 2 against a loopback URL; copy_out PNG; emit SSE.

    Skips cleanly when not useful (D31). Capture failure does not fail the job.
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise ScreenshotError(f"unknown job_id: {job_id}", code="not_found")

    ok, reason = should_capture_screenshots(job_id, settings=cfg)
    if not ok:
        _log(
            job_id,
            f"screenshot skipped ({reason})",
            settings=cfg,
            kind="screenshot",
            status="skipped",
            reason=reason,
        )
        return ScreenshotResult(job_id=job_id, status="skipped", reason=reason)

    environment_id = job.sandbox_id or ""
    profile = _current_runtime_profile(job_id, cfg)
    target = (url or _select_http_url(profile, job.readiness) or "").strip()
    if not target.startswith(("http://127.0.0.1", "http://localhost", "http://[::1]")):
        return ScreenshotResult(job_id=job_id, status="skipped", reason="non_loopback_url")

    shot_id = str(uuid.uuid4())
    guest_path = f"{GUEST_SHOT_DIR}/{shot_id}.png"
    site = f"{GUEST_TOOLING}/playwright/py"
    browsers = f"{GUEST_TOOLING}/playwright/browsers"

    # Resolve system chromium if present (set during ensure_playwright_tooling).
    which = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            "command -v chromium || command -v chromium-browser || true",
        ],
        job_id=job_id,
        settings=cfg,
        timeout=30,
    )
    chromium_path = (which.stdout or "").strip().splitlines()
    chromium_bin = chromium_path[0].strip() if chromium_path else ""

    env_exports = (
        f"export PYTHONPATH={site}${{PYTHONPATH:+:$PYTHONPATH}}; "
        f"export PLAYWRIGHT_BROWSERS_PATH={browsers}; "
        f"mkdir -p {GUEST_SHOT_DIR}; "
    )
    if chromium_bin:
        env_exports += f"export KILLHUB_CHROMIUM_PATH={chromium_bin}; "

    capture = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            env_exports + f"python3 {GUEST_HELPERS}/screenshot_capture.py "
            f"--url '{target}' --out '{guest_path}' --timeout-ms 20000",
        ],
        job_id=job_id,
        settings=cfg,
        timeout=90,
    )
    if capture.exit_code != 0:
        detail = ((capture.stderr or "") + (capture.stdout or ""))[:300]
        _log(
            job_id,
            "screenshot capture failed (non-fatal)",
            settings=cfg,
            kind="screenshot",
            status="failed",
            exit_code=capture.exit_code,
            detail=detail,
        )
        return ScreenshotResult(
            job_id=job_id,
            status="failed",
            reason=f"capture_exit_{capture.exit_code}",
        )

    try:
        host_path = copy_out(
            environment_id,
            guest_path,
            "screenshot",
            job_id=job_id,
            filename=f"{shot_id}.png",
            settings=cfg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("screenshot copy_out failed for %s", job_id)
        _log(
            job_id,
            "screenshot copy_out failed (non-fatal)",
            settings=cfg,
            kind="screenshot",
            status="failed",
            error=exc.__class__.__name__,
        )
        return ScreenshotResult(job_id=job_id, status="failed", reason="copy_out_failed")

    safe_caption = redact_caption(caption or f"HTTP verify still ({target})")
    # Optional vision caption on Plane-1 still only (D75). Never gates completion (D31).
    if getattr(cfg, "enable_screenshot_vision", False):
        try:
            from inference_extras import caption_screenshot

            vision_caption = caption_screenshot(host_path, job_id=job_id, settings=cfg)
            if vision_caption:
                safe_caption = redact_caption(vision_caption)
                _log(
                    job_id,
                    "screenshot vision caption applied",
                    settings=cfg,
                    kind="screenshot_vision",
                    status="ok",
                    screenshot_id=shot_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.info("screenshot vision skipped: %s", exc.__class__.__name__)
            _log(
                job_id,
                "screenshot vision skipped (non-fatal)",
                settings=cfg,
                kind="screenshot_vision",
                status="skipped",
                error=exc.__class__.__name__,
            )
    try:
        storage_ref = maybe_upload_local_file(
            host_path,
            kind="screenshot",
            job_id=job_id,
            filename=f"{shot_id}.png",
            content_type="image/png",
            settings=cfg,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("screenshot object upload failed for %s", job_id)
        _log(
            job_id,
            "screenshot object upload failed (non-fatal; keeping local)",
            settings=cfg,
            kind="screenshot",
            status="upload_failed",
            error=exc.__class__.__name__,
        )
        storage_ref = str(host_path)
    meta = ledger.insert_screenshot(
        job_id,
        screenshot_id=shot_id,
        step=step,
        caption=safe_caption,
        storage_path=storage_ref,
    )
    public = {
        "screenshot_id": shot_id,
        "step": step,
        "caption": safe_caption,
        "url": public_screenshot_url(
            job_id,
            shot_id,
            storage_path=storage_ref,
            settings=cfg,
        ),
        "bytes": host_path.stat().st_size if host_path.is_file() else 0,
        "at": utc_now(),
    }
    ledger.append_event(
        job_id,
        typ="screenshot",
        message=safe_caption,
        payload=public,
    )
    _log(
        job_id,
        f"screenshot captured {shot_id}",
        settings=cfg,
        kind="screenshot",
        status="captured",
        screenshot_id=shot_id,
        step=step,
    )
    # Best-effort: remove guest copy (host retains the still).
    exec_command(
        environment_id,
        ["rm", "-f", guest_path],
        job_id=job_id,
        settings=cfg,
        timeout=15,
    )
    return ScreenshotResult(
        job_id=job_id,
        status="captured",
        reason="ok",
        screenshots=[{**meta, **public}],
    )


def maybe_capture_after_verify(
    job_id: str,
    *,
    settings: Settings | None = None,
) -> ScreenshotResult:
    """Worker entry: never raises into a job-failing path for skip/capture miss."""
    cfg = settings or get_settings()
    try:
        return capture_http_screenshot(job_id, settings=cfg, step="verify")
    except ScreenshotError as exc:
        _log(
            job_id,
            f"screenshot aborted: {exc.message}",
            settings=cfg,
            kind="screenshot",
            status="failed",
            code=exc.code,
        )
        return ScreenshotResult(job_id=job_id, status="failed", reason=exc.code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("screenshot unexpected failure for %s", job_id)
        _log(
            job_id,
            f"screenshot unexpected error: {exc.__class__.__name__}",
            settings=cfg,
            kind="screenshot",
            status="failed",
        )
        return ScreenshotResult(
            job_id=job_id,
            status="failed",
            reason=exc.__class__.__name__,
        )
