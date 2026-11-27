"""Install-phase provision → deny-all remaining egress (D43, D63, D29, D65).

Does not mark the job completed. Readiness is plan 14.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from profile import GUEST_REPO_ROOT, assert_runtime_ready_for_provision
from typing import Any

from config import Settings, get_settings
from harness import MsbCli, copy_in, exec_command, wait_until_ready
from heartbeat import with_heartbeat
from jobs import get_ledger
from net_policy import verify_phase_policy
from paths import HELPER_CATALOG

logger = logging.getLogger("killhub.install")

GUEST_HELPERS = "/opt/killhub/helpers"
GUEST_TOOLING = "/opt/killhub/tooling"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    exit_code: int | None = None


@dataclass
class InstallResult:
    job_id: str
    environment_id: str
    network_phase: str
    steps: list[StepResult] = field(default_factory=list)
    tooling: dict[str, Any] = field(default_factory=dict)
    install_failures: list[str] = field(default_factory=list)
    cp_probe: dict[str, Any] = field(default_factory=dict)
    offline_probe: dict[str, Any] = field(default_factory=dict)
    repair_attempts: int = 0


class InstallError(Exception):
    def __init__(self, message: str, *, code: str = "install_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _current_runtime_profile(job_id: str, settings: Settings) -> dict[str, Any]:
    ledger = get_ledger(settings)
    job = ledger.get_job(job_id)
    if job is None:
        raise InstallError(f"unknown job_id: {job_id}", code="not_found")
    revs = ledger.list_profile_revisions(job_id)
    runtime = [r for r in revs if r.phase == "runtime"]
    if not runtime:
        raise InstallError("no runtime profile revision", code="no_runtime_profile")
    profile = runtime[-1].profile
    assert_runtime_ready_for_provision(profile)
    return profile


def _log(
    job_id: str,
    message: str,
    *,
    settings: Settings,
    kind: str,
    **payload: Any,
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": kind, **payload},
    )


def _finding(
    job_id: str,
    message: str,
    *,
    settings: Settings,
    source: str,
    code: str,
    severity: str = "medium",
    **extra: Any,
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="finding",
        message=message,
        payload={
            "source": source,
            "code": code,
            "severity": severity,
            **extra,
        },
    )


def _status(
    job_id: str,
    status: str,
    *,
    settings: Settings,
    step: str,
    progress: int,
) -> None:
    ledger = get_ledger(settings)
    ledger.update_job_fields(
        job_id,
        status=status,
        current_step=step,
        progress=progress,
    )
    ledger.append_event(
        job_id,
        typ="status",
        message=step,
        payload={
            "status": status,
            "step": step,
            "current_step": step,
            "progress": progress,
        },
    )


def _run_command_spec(
    environment_id: str,
    spec: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    default_cwd: str,
) -> StepResult:
    timeout = float(spec.get("timeout_seconds") or 120)
    cwd = str(spec.get("cwd") or default_cwd)
    if spec.get("argv"):
        argv = [str(x) for x in spec["argv"]]
        # Run under sh so cwd applies portably.
        cmd = ["sh", "-lc", f"cd {cwd} && exec " + " ".join(_shell_quote(a) for a in argv)]
        label = " ".join(argv[:6])
    elif spec.get("shell"):
        cmd = ["sh", "-lc", f"cd {cwd} && {spec['shell']}"]
        label = str(spec["shell"])[:80]
    else:
        return StepResult(name="invalid", ok=False, detail="missing argv/shell")
    result = exec_command(
        environment_id,
        cmd,
        job_id=job_id,
        settings=settings,
        timeout=timeout,
    )
    ok = result.exit_code == 0
    detail = (result.stderr or result.stdout or "")[:400]
    return StepResult(name=label, ok=ok, detail=detail, exit_code=result.exit_code)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _host_fetch_ok(url: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "killhub-install-probe/0.1"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(code) < 400, f"http_{code}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return False, f"{exc.__class__.__name__}"


def _guest_fetch(
    environment_id: str,
    url: str,
    *,
    job_id: str,
    settings: Settings,
    timeout: float = 5.0,
) -> tuple[str, int]:
    """Return (classification, exit_code). classification: ok|denied|tooling_missing|infra."""
    # Ensure probe helper is present; fall back to inline wget/curl.
    result = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            f"if [ -x {GUEST_HELPERS}/network_probe.sh ]; then "
            f"{GUEST_HELPERS}/network_probe.sh {_shell_quote(url)} {int(timeout)}; "
            f"elif command -v wget >/dev/null 2>&1; then "
            f"wget -qO- --timeout={int(timeout)} {_shell_quote(url)} >/dev/null; "
            f"elif command -v curl >/dev/null 2>&1; then "
            f"curl -fsS --max-time {int(timeout)} {_shell_quote(url)} >/dev/null; "
            f"else echo tooling_missing; exit 3; fi",
        ],
        job_id=job_id,
        settings=settings,
        timeout=timeout + 15,
    )
    text = (result.stdout or "") + (result.stderr or "")
    if result.exit_code == 0:
        return "ok", 0
    if result.exit_code == 3 or "tooling_missing" in text:
        return "tooling_missing", result.exit_code
    # Denied / unreachable — distinguish later with positive control.
    return "denied", result.exit_code


def probe_control_plane_during_install(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """D65: known-live CP target + host positive control while install egress is open."""
    cfg = settings
    target = (cfg.control_plane_probe_url or "").strip()
    egress = (cfg.install_egress_probe_url or "").strip() or "https://example.com"
    if not target:
        return {"classification": "inconclusive", "reason": "no_probe_url"}

    host_ok, host_detail = _host_fetch_ok(target)
    guest_class, guest_code = _guest_fetch(environment_id, target, job_id=job_id, settings=cfg)
    # Positive control: guest can still reach a permitted public URL.
    egress_class, _ = _guest_fetch(environment_id, egress, job_id=job_id, settings=cfg)

    if not host_ok:
        classification = "inconclusive"
        reason = "host_positive_control_failed"
    elif guest_class == "tooling_missing":
        classification = "tooling_missing"
        reason = "guest_fetch_tool_missing"
    elif guest_class == "ok":
        classification = "policy_bypass"
        reason = "guest_reached_control_plane"
    elif egress_class == "ok":
        classification = "policy_denied"
        reason = "guest_denied_cp_while_egress_works"
    else:
        classification = "infra_error"
        reason = "guest_denied_cp_and_egress"

    evidence = {
        "phase": "install",
        "target": target,
        "host_ok": host_ok,
        "host_detail": host_detail,
        "guest_class": guest_class,
        "guest_exit": guest_code,
        "egress_probe": egress,
        "egress_class": egress_class,
        "classification": classification,
        "reason": reason,
        "probe_session": "install_cp_deny",
    }
    _log(
        job_id,
        f"install CP probe → {classification}",
        settings=cfg,
        kind="network_probe",
        **evidence,
    )
    if classification == "policy_denied":
        _finding(
            job_id,
            "control-plane egress denied during install (expected)",
            settings=cfg,
            source="network",
            code="cp_denied_install",
            severity="info",
            classification=classification,
            probe_session="install_cp_deny",
        )
    elif classification == "policy_bypass":
        _finding(
            job_id,
            "control-plane reachable from guest during install",
            settings=cfg,
            source="network",
            code="cp_bypass_install",
            severity="critical",
            classification=classification,
            probe_session="install_cp_deny",
        )
    return evidence


def preinstall_assessment_tooling(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """Copy Killhub helpers + mark tooling dirs before offline (D63)."""
    for helper_id, rel in HELPER_CATALOG.items():
        copy_in(
            environment_id,
            helper_id,
            f"{GUEST_HELPERS}/{rel}",
            job_id=job_id,
            settings=settings,
        )

    # Ensure executable bits + tooling placeholder dirs.
    exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            f"mkdir -p {GUEST_HELPERS} {GUEST_TOOLING}/playwright "
            f"{GUEST_TOOLING}/mcp-inspector && "
            f"chmod +x {GUEST_HELPERS}/*.sh {GUEST_HELPERS}/*.py 2>/dev/null || true",
        ],
        job_id=job_id,
        settings=settings,
        timeout=60,
    )
    # Best-effort: install wget/curl for probes if missing (install egress still open).
    with_heartbeat(
        job_id,
        settings=settings,
        label="installing probe packages",
        fn=lambda: exec_command(
            environment_id,
            [
                "sh",
                "-lc",
                "if command -v wget >/dev/null 2>&1 || command -v curl >/dev/null 2>&1; then "
                "exit 0; "
                "elif command -v apt-get >/dev/null 2>&1; then "
                "export DEBIAN_FRONTEND=noninteractive; "
                "apt-get update -qq && "
                "apt-get install -y -qq python3 wget curl ca-certificates; "
                "elif command -v apk >/dev/null 2>&1; then "
                "apk add --no-cache python3 wget curl ca-certificates; "
                "else exit 0; fi",
            ],
            job_id=job_id,
            settings=settings,
            timeout=300,
        ),
    )
    probe = exec_command(
        environment_id,
        ["sh", "-lc", f"{GUEST_HELPERS}/tooling_probe.sh"],
        job_id=job_id,
        settings=settings,
        timeout=60,
    )
    tooling = {
        "probe_exit": probe.exit_code,
        "probe_out": (probe.stdout or "")[:1000],
        "helpers_root": GUEST_HELPERS,
    }
    _log(
        job_id,
        "assessment tooling preinstalled",
        settings=settings,
        kind="install",
        tooling=tooling,
    )
    if probe.exit_code != 0:
        _finding(
            job_id,
            "Killhub helper probe reported missing files",
            settings=settings,
            source="install",
            code="tooling_incomplete",
            severity="high",
            detail=tooling["probe_out"][:300],
        )
    return tooling


def _attempt_packages(
    environment_id: str,
    packages: list[Any],
    *,
    job_id: str,
    settings: Settings,
) -> list[StepResult]:
    results: list[StepResult] = []
    names = [str(p) for p in packages if str(p).strip()]
    if not names:
        return results
    joined = " ".join(_shell_quote(n) for n in names)
    script = (
        "if command -v apt-get >/dev/null 2>&1; then "
        "export DEBIAN_FRONTEND=noninteractive; "
        f"apt-get update -qq && apt-get install -y -qq {joined}; "
        "elif command -v apk >/dev/null 2>&1; then "
        f"apk add --no-cache {joined}; "
        "elif command -v npm >/dev/null 2>&1; then "
        f"npm install -g {joined}; "
        "else echo 'no package manager for packages[]' >&2; exit 1; fi"
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", script],
        job_id=job_id,
        settings=settings,
        timeout=600,
    )
    results.append(
        StepResult(
            name=f"packages:{','.join(names[:8])}",
            ok=result.exit_code == 0,
            detail=(result.stderr or result.stdout or "")[:400],
            exit_code=result.exit_code,
        )
    )
    return results


def run_install_commands(
    environment_id: str,
    profile: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> list[StepResult]:
    """Attempt packages + install_commands — flag failures, never invent success (D29)."""
    steps: list[StepResult] = []
    workdir = str(profile.get("workdir") or GUEST_REPO_ROOT)
    steps.extend(
        _attempt_packages(
            environment_id,
            list(profile.get("packages") or []),
            job_id=job_id,
            settings=settings,
        )
    )
    for i, spec in enumerate(profile.get("install_commands") or []):
        if not isinstance(spec, dict):
            steps.append(
                StepResult(name=f"install_commands[{i}]", ok=False, detail="not an object")
            )
            continue
        if getattr(settings, "active_checks", True):
            # Active checks: trace each install command (guest-side strace).
            from activity import wrap_command_spec

            spec = wrap_command_spec(spec, i)
        step = _run_command_spec(
            environment_id,
            spec,
            job_id=job_id,
            settings=settings,
            default_cwd=workdir,
        )
        steps.append(step)
        _log(
            job_id,
            f"install step {'ok' if step.ok else 'FAILED'}: {step.name}",
            settings=settings,
            kind="install",
            ok=step.ok,
            exit_code=step.exit_code,
            detail=step.detail[:200],
        )
        if not step.ok:
            _finding(
                job_id,
                f"install command failed: {step.name}",
                settings=settings,
                source="install",
                code="install_command_failed",
                severity="high",
                exit_code=step.exit_code,
                detail=step.detail[:300],
            )
    return steps


def transition_to_verify_offline(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
    cli: MsbCli | None = None,
) -> dict[str, Any]:
    """
    Snapshot → remove → restore with --no-net (deny-all remaining egress) (D43).

    Preserves guest disk (installed deps + helpers). Still one live sandbox.
    """
    cfg = settings
    msb = cli or MsbCli(cfg)
    policy = verify_phase_policy()
    group = f"kh-snap-{job_id.replace('-', '')[:40]}"
    _log(
        job_id,
        "transitioning to deny-all remaining egress",
        settings=cfg,
        kind="network_phase",
        phase="verify",
        policy="no-net",
    )
    # Best-effort cleanup of prior group.
    msb.snapshot_remove_group(group)
    with_heartbeat(
        job_id,
        settings=cfg,
        label="creating install snapshot",
        fn=lambda: msb.snapshot_create(
            group, sandbox=environment_id, checkpoint="post-install", full=True
        ),
    )
    # Remove install-phase VM before restore (never two concurrent).
    stop = msb.stop(environment_id, force=False)
    remove = msb.remove(environment_id, force=True)
    if not remove.ok and "not found" not in (remove.stderr + remove.stdout).lower():
        raise InstallError(
            f"failed to remove sandbox before offline restore: {remove.stderr[:200]}",
            code="offline_remove_failed",
        )
    with_heartbeat(
        job_id,
        settings=cfg,
        label="restoring offline snapshot",
        fn=lambda: msb.snapshot_restore_offline(group, name=environment_id),
    )
    wait_until_ready(environment_id, settings=cfg, cli=msb, job_id=job_id)
    # Update phase label for operators.
    msb.run(
        ["modify", environment_id, "--label", f"killhub.net_phase={policy.phase}"],
        timeout=60,
        check=False,
    )
    get_ledger(cfg).append_event(
        job_id,
        typ="lifecycle",
        message="network phase → verify (deny-all remaining egress)",
        payload={
            "phase": "network_verify",
            "environment_id": environment_id,
            "snapshot_group": group,
            "net": {"no_net": True, "phase": policy.phase},
            "stop_ok": stop.ok,
        },
    )
    return {"snapshot_group": group, "phase": policy.phase}


def probe_offline_egress(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """Confirm public egress fails after verify transition; log finding."""
    url = (settings.install_egress_probe_url or "https://example.com").strip()
    classification, code = _guest_fetch(
        environment_id, url, job_id=job_id, settings=settings, timeout=5
    )
    if classification == "ok":
        result = {
            "classification": "policy_bypass",
            "url": url,
            "guest_exit": code,
        }
        _finding(
            job_id,
            "public egress still reachable after deny-all transition",
            settings=settings,
            source="network",
            code="offline_bypass",
            severity="critical",
            **result,
        )
    elif classification == "tooling_missing":
        result = {
            "classification": "tooling_missing",
            "url": url,
            "guest_exit": code,
        }
        _finding(
            job_id,
            "offline probe missing wget/curl",
            settings=settings,
            source="network",
            code="offline_tooling_missing",
            severity="medium",
            **result,
        )
    else:
        result = {
            "classification": "policy_denied",
            "url": url,
            "guest_exit": code,
        }
        _finding(
            job_id,
            "public egress denied after verify-phase transition (expected)",
            settings=settings,
            source="network",
            code="offline_denied",
            severity="info",
            **result,
        )
        _log(
            job_id,
            "denied egress attempt observed",
            settings=settings,
            kind="network_probe",
            phase="verify",
            **result,
        )
    return result


def provision_and_go_offline(
    job_id: str,
    *,
    settings: Settings | None = None,
    cli: MsbCli | None = None,
) -> InstallResult:
    """
    Run install under install egress, preinstall tooling, CP probe, then offline.

    Repair retries install_commands only (capped by MAX_REPAIR_ATTEMPTS).
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise InstallError(f"unknown job_id: {job_id}", code="not_found")
    if not job.sandbox_id:
        raise InstallError("no live sandbox for install", code="no_sandbox")
    environment_id = job.sandbox_id
    profile = _current_runtime_profile(job_id, cfg)
    msb = cli or MsbCli(cfg)

    _status(
        job_id,
        "installing",
        settings=cfg,
        step="install phase",
        progress=max(job.progress, 70),
    )

    tooling = preinstall_assessment_tooling(environment_id, job_id=job_id, settings=cfg)
    # Playwright browsers for optional HTTP stills (D63) — install-phase egress only.
    intent = str(profile.get("intent") or "")
    if intent in {"webapp", "demo"} or (
        intent == "git_mcp" and (profile.get("mcp") or {}).get("transport") == "streamable_http"
    ):
        from screenshots import ensure_playwright_tooling

        tooling["playwright"] = ensure_playwright_tooling(
            environment_id,
            job_id=job_id,
            settings=cfg,
            intent=intent,
        )
    cp_probe = probe_control_plane_during_install(environment_id, job_id=job_id, settings=cfg)
    if cp_probe.get("classification") == "policy_bypass":
        raise InstallError(
            "control-plane reachable from guest during install",
            code="cp_bypass",
        )

    active = getattr(cfg, "active_checks", True)
    if active:
        from activity import prepare_guest

        try:
            prepare_guest(environment_id, job_id=job_id, settings=cfg)
        except Exception as exc:  # noqa: BLE001 — tracing is best-effort, never blocks install
            _log(
                job_id, f"activity trace unavailable: {exc}", settings=cfg, kind="install_activity"
            )

    max_attempts = max(int(cfg.max_repair_attempts or 1), 1)
    steps: list[StepResult] = []
    failures: list[str] = []
    attempt = 0
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            _status(
                job_id,
                "repairing",
                settings=cfg,
                step=f"install repair attempt {attempt}",
                progress=max(job.progress, 72),
            )
            _log(
                job_id,
                f"install repair attempt {attempt}",
                settings=cfg,
                kind="repair",
                attempt=attempt,
            )
        steps = run_install_commands(environment_id, profile, job_id=job_id, settings=cfg)
        failures = [s.name for s in steps if not s.ok]
        if not failures:
            break
        # D80: repairs against a vanished VM can never succeed — hand the loss
        # to the worker's self-heal instead of burning the remaining attempts.
        from selfheal import sandbox_alive

        if sandbox_alive(environment_id, cli=msb) is False:
            raise InstallError(
                f"sandbox lost during install: {environment_id}",
                code="sandbox_lost",
            )

    if active:
        from activity import collect_and_analyze

        try:
            collect_and_analyze(environment_id, job_id=job_id, settings=cfg)
        except Exception as exc:  # noqa: BLE001 — report, never invent "no activity"
            _log(job_id, f"activity analysis failed: {exc}", settings=cfg, kind="install_activity")

    offline_meta = transition_to_verify_offline(
        environment_id, job_id=job_id, settings=cfg, cli=msb
    )
    offline_probe = probe_offline_egress(environment_id, job_id=job_id, settings=cfg)

    _status(
        job_id,
        "verifying",
        settings=cfg,
        step="install done; deny-all egress active",
        progress=80,
    )
    _log(
        job_id,
        "install phase complete; verify network phase active",
        settings=cfg,
        kind="install",
        failures=failures,
        repair_attempts=attempt,
        offline=offline_meta,
        offline_probe=offline_probe,
    )

    return InstallResult(
        job_id=job_id,
        environment_id=environment_id,
        network_phase="verify",
        steps=steps,
        tooling=tooling,
        install_failures=failures,
        cp_probe=cp_probe,
        offline_probe=offline_probe,
        repair_attempts=attempt,
    )
