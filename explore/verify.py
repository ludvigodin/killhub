"""Readiness verify + verification kinds (D30, D37, D47, D54, D62, D66).

Sets `readiness` / `verification` from real probes. Never marks `completed`
and never destroys the sandbox (D37).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from profile import (
    DEFAULT_MAX_RESTARTS,
    GUEST_REPO_ROOT,
    SUPERVISE_MODES,
    ProfileError,
    assert_runtime_ready_for_provision,
    command_spec_shell,
    effective_processes,
    env_exports,
    persist_profile_revision,
    probe_type,
    profile_probes,
    resolve_guest_path,
    service_launch_order,
    shell_quote,
)
from typing import Any

from config import Settings, get_settings
from harness import copy_in, exec_command
from jobs import get_ledger
from ledger.store import utc_now
from plan_llm import deadline_exceeded

logger = logging.getLogger("killhub.verify")

GUEST_HELPERS = "/opt/killhub/helpers"
_NPX_Y_RE = re.compile(r"\bnpx\b.*\s-y\b|\bnpx\b.*\s--yes\b", re.IGNORECASE)


@dataclass
class VerifyResult:
    job_id: str
    environment_id: str
    passed: bool
    verification_kind: str
    readiness: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    verify_result: dict[str, Any] = field(default_factory=dict)
    destroyed: bool = False
    completed: bool = False


class VerifyError(Exception):
    def __init__(self, message: str, *, code: str = "verify_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


_shell_quote = shell_quote


def _log(job_id: str, message: str, *, settings: Settings, kind: str, **payload: Any) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": kind, **payload},
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
        message=status,
        payload={"status": status, "step": step},
    )


def _current_runtime_profile(job_id: str, settings: Settings) -> dict[str, Any]:
    ledger = get_ledger(settings)
    job = ledger.get_job(job_id)
    if job is None:
        raise VerifyError(f"unknown job_id: {job_id}", code="not_found")
    revs = ledger.list_profile_revisions(job_id)
    runtime = [r for r in revs if r.phase == "runtime"]
    if not runtime:
        raise VerifyError("no runtime profile revision", code="no_runtime_profile")
    profile = runtime[-1].profile
    assert_runtime_ready_for_provision(profile)
    return profile


def command_spec_tokens(spec: dict[str, Any]) -> list[str]:
    if spec.get("argv"):
        return [str(x) for x in spec["argv"]]
    if spec.get("shell"):
        return str(spec["shell"]).split()
    return []


def assert_built_checkout_launch(
    profile: dict[str, Any],
    *,
    resolved_commit: str | None,
) -> None:
    """Reject unpinned registry launches for original_application (D62)."""
    target = profile.get("verification_target")
    if target != "original_application":
        return
    if not resolved_commit or not re.fullmatch(r"[0-9a-f]{40}", resolved_commit):
        raise VerifyError(
            "original_application requires resolved_commit SHA (D62)",
            code="missing_commit",
        )
    source = profile.get("source") or {}
    if source.get("commit") != resolved_commit:
        raise VerifyError(
            "profile source.commit must equal resolved_commit (D62)",
            code="commit_mismatch",
        )

    specs: list[dict[str, Any]] = []
    for key in ("run_commands", "install_commands"):
        for item in profile.get(key) or []:
            if isinstance(item, dict):
                specs.append(item)
    for proc in profile.get("processes") or []:
        if isinstance(proc, dict) and isinstance(proc.get("command"), dict):
            specs.append(proc["command"])
    mcp = profile.get("mcp") if isinstance(profile.get("mcp"), dict) else {}
    if isinstance(mcp.get("launch_command"), dict):
        specs.append(mcp["launch_command"])

    for spec in specs:
        tokens = command_spec_tokens(spec)
        joined = " ".join(tokens)
        shell = str(spec.get("shell") or "")
        blob = f"{joined} {shell}"
        if _NPX_Y_RE.search(blob) or re.search(r"\bnpx\b.*\s-y\b", shell, re.I):
            raise VerifyError(
                "original_application forbids unpinned npx -y launches (D62)",
                code="unpinned_registry_launch",
            )
        if "npx" in tokens and ("-y" in tokens or "--yes" in tokens):
            raise VerifyError(
                "original_application forbids unpinned npx -y launches (D62)",
                code="unpinned_registry_launch",
            )


_SUPERVISOR = r"""
d="$KH_DIR/$KH_NAME"
rm -f "$d.stop" "$d.exit" "$d.state"
n=0
while :; do
  if [ "$KH_TIMEOUT" -gt 0 ] && command -v timeout >/dev/null 2>&1; then
    timeout -s TERM "$KH_TIMEOUT" sh -c "$KH_CMD" >>"$d.log" 2>&1 &
  else
    sh -c "$KH_CMD" >>"$d.log" 2>&1 &
  fi
  echo $! >"$d.child"
  wait $!
  code=$?
  echo "$code" >"$d.exit"
  if [ -f "$d.stop" ]; then echo stopped >"$d.state"; exit 0; fi
  if [ "$KH_MODE" != restart ]; then echo exited >"$d.state"; exit 0; fi
  n=$((n+1))
  echo "$n" >"$d.restarts"
  if [ "$n" -gt "$KH_MAX" ]; then echo gave_up >"$d.state"; exit 1; fi
  echo "[killhub] restart $n after exit $code" >>"$d.log"
  sleep 1
done
"""

# Walk children with pgrep when present so `npm start` -> node trees stop together.
_KILL_TREE = (
    'kh_kill_tree() { for c in $(pgrep -P "$1" 2>/dev/null); do kh_kill_tree "$c" "$2"; done; '
    'kill -s "$2" "$1" 2>/dev/null; }; '
)
_GUEST_DIR = "/tmp/killhub"
# Services are considered up only once their declared ports accept connections.
SERVICE_PORT_WAIT = {"retries": 30, "interval_seconds": 1, "timeout_seconds": 2}


def _spec_to_shell(spec: dict[str, Any], *, default_cwd: str) -> str:
    try:
        return command_spec_shell(spec, workdir=default_cwd)
    except ProfileError as exc:
        raise VerifyError(exc.message, code="invalid_command") from exc


def _proc_path(name: str, suffix: str) -> str:
    return f"{_GUEST_DIR}/{name}.{suffix}"


def launch_supervised_process(
    environment_id: str,
    process: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    default_cwd: str,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start a profile process in the guest under the declared supervision (P2).

    ``supervise=restart`` re-runs the command after it exits (1s apart, at most
    ``max_restarts`` times, default 3) and records ``gave_up`` when that budget is spent.
    ``oneshot`` runs it once. The command's ``cwd``/``env`` and ``timeout_seconds`` (maximum
    lifetime per invocation, via ``timeout`` when present) are honored. Stop with
    ``stop_supervised_process`` (``stop_signal``, then SIGKILL).
    """
    name = str(process.get("name") or "app")
    command = process.get("command")
    if not isinstance(command, dict):
        raise VerifyError(f"process {name} missing command", code="invalid_process")
    mode = str(process.get("supervise") or "oneshot")
    if mode not in SUPERVISE_MODES:
        raise VerifyError(f"process {name}: unsupported supervise {mode!r}", code="invalid_process")
    stop_signal = str(process.get("stop_signal") or "SIGTERM")
    max_restarts = int(process.get("max_restarts", DEFAULT_MAX_RESTARTS))
    # Profile-level defaults (e.g. PORT) sit under the command's own env.
    merged = {**command, "env": {**(extra_env or {}), **(command.get("env") or {})}}
    shell = _spec_to_shell(merged, default_cwd=default_cwd)
    timeout = int(float(command.get("timeout_seconds") or 0))
    log_path = _proc_path(name, "log")
    pid_path = _proc_path(name, "pid")
    script = (
        f"mkdir -p {_GUEST_DIR} && "
        f"export KH_DIR={_GUEST_DIR} KH_NAME={shell_quote(name)} KH_MODE={mode} "
        f"KH_MAX={max_restarts} KH_TIMEOUT={timeout} KH_CMD={shell_quote(shell)} && "
        f"nohup sh -c {shell_quote(_SUPERVISOR)} >/dev/null 2>&1 & "
        f"echo $! >{shell_quote(pid_path)} && cat {shell_quote(pid_path)}"
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", script],
        job_id=job_id,
        settings=settings,
        timeout=60,
    )
    if result.exit_code != 0:
        raise VerifyError(
            f"failed to launch process {name}: {(result.stderr or result.stdout)[:300]}",
            code="launch_failed",
        )
    pid = (result.stdout or "").strip().splitlines()[-1].strip() if result.stdout else ""
    delay = float(process["ready_after_seconds"] if "ready_after_seconds" in process else 1)
    if delay > 0:
        exec_command(
            environment_id,
            ["sh", "-lc", f"sleep {delay}"],
            job_id=job_id,
            settings=settings,
            timeout=delay + 15,
        )
    state = _supervised_state(environment_id, name, pid, job_id=job_id, settings=settings)
    handle = {
        "name": name,
        "pid": pid,
        "log_path": log_path,
        "supervise": mode,
        "stop_signal": stop_signal,
        "state": state,
    }
    _log(
        job_id,
        f"launched process {name} pid={pid} supervise={mode}",
        settings=settings,
        kind="verify",
        process=name,
        pid=pid,
        log_path=log_path,
        supervise=mode,
        max_restarts=max_restarts if mode == "restart" else None,
        stop_signal=stop_signal,
        ready_probe=process.get("ready_probe"),
        state=state,
    )
    # Dead already (crashed, gave up restarting, or oneshot with a failing exit): not ready.
    if state.get("alive") is False and not (mode == "oneshot" and state.get("exit_code") == 0):
        tail = _log_tail(environment_id, name, job_id=job_id, settings=settings)
        raise VerifyError(
            f"process {name} is not running (state={state.get('state')}, "
            f"exit={state.get('exit_code')}): {tail}",
            code="process_exited",
        )
    return handle


def _supervised_state(
    environment_id: str, name: str, pid: str, *, job_id: str, settings: Settings
) -> dict[str, Any]:
    """Observed supervisor state: alive flag, last exit code, restart count, final state."""
    if not pid.isdigit():
        return {}
    script = (
        f'if kill -0 {pid} 2>/dev/null; then echo "kh_alive:1"; else echo "kh_alive:0"; fi; '
        f'echo "kh_state:$(cat {_proc_path(name, "state")} 2>/dev/null)"; '
        f'echo "kh_exit:$(cat {_proc_path(name, "exit")} 2>/dev/null)"; '
        f'echo "kh_restarts:$(cat {_proc_path(name, "restarts")} 2>/dev/null)"'
    )
    result = exec_command(
        environment_id, ["sh", "-lc", script], job_id=job_id, settings=settings, timeout=30
    )
    fields: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if line.startswith("kh_") and ":" in line:
            key, _, value = line.partition(":")
            fields[key] = value.strip()
    if "kh_alive" not in fields:
        return {}
    exit_raw = fields.get("kh_exit", "")
    return {
        "alive": fields["kh_alive"] == "1",
        "state": fields.get("kh_state") or ("running" if fields["kh_alive"] == "1" else "dead"),
        "exit_code": int(exit_raw) if exit_raw.lstrip("-").isdigit() else None,
        "restarts": int(fields["kh_restarts"]) if fields.get("kh_restarts", "").isdigit() else 0,
    }


def _log_tail(environment_id: str, name: str, *, job_id: str, settings: Settings) -> str:
    result = exec_command(
        environment_id,
        ["sh", "-lc", f"tail -c 400 {shell_quote(_proc_path(name, 'log'))} 2>/dev/null || true"],
        job_id=job_id,
        settings=settings,
        timeout=15,
    )
    return (result.stdout or "")[-400:]


def stop_supervised_process(
    environment_id: str,
    handle: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """Stop a launched process tree: ``stop_signal``, short grace, then SIGKILL (cleanup)."""
    name = str(handle["name"])
    sig = str(handle.get("stop_signal") or "SIGTERM").removeprefix("SIG")
    pid = str(handle.get("pid") or "")
    sup = pid if pid.isdigit() else ""
    child_file = shell_quote(_proc_path(name, "child"))
    script = (
        f"{_KILL_TREE}"
        f"touch {shell_quote(_proc_path(name, 'stop'))}; "
        f"child=$(cat {child_file} 2>/dev/null); "
        f'if [ -n "$child" ]; then kh_kill_tree "$child" {sig}; fi; '
        "i=0; while [ $i -lt 5 ]; do "
        f'if [ -n "$child" ] && kill -0 "$child" 2>/dev/null; then sleep 1; i=$((i+1)); '
        "else break; fi; done; "
        f'if [ -n "$child" ] && kill -0 "$child" 2>/dev/null; then kh_kill_tree "$child" KILL; fi; '
        + (f"kill -s TERM {sup} 2>/dev/null; " if sup else "")
        + "echo kh_stopped"
    )
    result = exec_command(
        environment_id, ["sh", "-lc", script], job_id=job_id, settings=settings, timeout=60
    )
    detail = {"name": name, "stop_signal": f"SIG{sig}", "ok": result.exit_code == 0}
    _log(job_id, f"stopped process {name}", settings=settings, kind="verify_cleanup", **detail)
    return detail


def stop_all(
    environment_id: str,
    handles: list[dict[str, Any]],
    *,
    job_id: str,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Reverse launch order (processes before the services they depend on)."""
    out: list[dict[str, Any]] = []
    for handle in reversed(handles):
        try:
            out.append(
                stop_supervised_process(environment_id, handle, job_id=job_id, settings=settings)
            )
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort, never masks the verdict
            out.append({"name": handle.get("name"), "ok": False, "error": str(exc)[:200]})
    return out


# --- probes: http | tcp | command (explicit pass criteria) -------------------------------

DEFAULT_HTTP_ACCEPT = tuple(range(200, 400))


def probe_http(
    environment_id: str,
    probe: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """Pass: status in ``accept`` (default 200-399) and, if set, body contains ``body_contains``."""
    url = str(probe.get("url") or "").strip()
    if not url:
        raise VerifyError("http probe missing url", code="invalid_probe")
    timeout = float(probe.get("timeout_seconds") or 10)
    accept = probe.get("accept")
    accept_set = {int(x) for x in accept} if accept else set(DEFAULT_HTTP_ACCEPT)
    body_contains = str(probe.get("body_contains") or "")
    body_check = (
        f"if grep -qF -- {shell_quote(body_contains)} /tmp/killhub-http-probe.out; "
        'then echo "body_match:1"; else echo "body_match:0"; fi; '
        if body_contains
        else ""
    )
    # Prefer curl -w for a reliable status; wget as fallback.
    script = (
        f"URL={_shell_quote(url)}; "
        "if command -v curl >/dev/null 2>&1; then "
        f"code=$(curl -sS -o /tmp/killhub-http-probe.out -w '%{{http_code}}' "
        f'--max-time {max(1, int(timeout))} "$URL" || echo 000); '
        'echo "http_code:$code"; '
        "elif command -v wget >/dev/null 2>&1; then "
        f'wget -S -O /tmp/killhub-http-probe.out --timeout={max(1, int(timeout))} "$URL" '
        ">/tmp/killhub-http-probe.hdr 2>&1 || true; "
        "code=$(awk 'BEGIN{c=0} /HTTP\\//{c=$2} END{print c+0}' "
        "/tmp/killhub-http-probe.hdr); "
        'echo "http_code:$code"; '
        "else echo tooling_missing; exit 3; fi; " + body_check
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", script],
        job_id=job_id,
        settings=settings,
        timeout=timeout + 20,
    )
    text = (result.stdout or "") + "\n" + (result.stderr or "")
    if "tooling_missing" in text or result.exit_code == 3:
        return {
            "ok": False,
            "probe": probe.get("name") or url,
            "type": "http",
            "url": url,
            "error": "tooling_missing",
        }
    code = None
    for line in text.splitlines():
        if "http_code:" in line:
            try:
                code = int(line.split("http_code:", 1)[1].strip().split()[0])
            except ValueError:
                code = None
    status_ok = code is not None and code in accept_set
    body_ok = (not body_contains) or "body_match:1" in text
    ok = status_ok and body_ok
    log_snip = ""
    if not ok:
        log_read = exec_command(
            environment_id,
            [
                "sh",
                "-lc",
                "tail -c 400 /tmp/killhub/web.log 2>/dev/null || "
                "tail -c 400 /tmp/killhub/*.log 2>/dev/null || true",
            ],
            job_id=job_id,
            settings=settings,
            timeout=15,
        )
        log_snip = (log_read.stdout or "")[:400]
    return {
        "ok": ok,
        "probe": probe.get("name") or url,
        "type": "http",
        "url": url,
        "http_code": code,
        "accept": sorted(accept_set) if accept else "200-399",
        "body_contains": body_contains or None,
        "body_matched": body_ok if body_contains else None,
        "exit_code": result.exit_code,
        "log_snip": log_snip,
    }


def probe_tcp(
    environment_id: str,
    probe: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """Pass: a TCP connect to host:port (default 127.0.0.1) succeeds within the timeout."""
    host = str(probe.get("host") or "127.0.0.1")
    port = probe.get("port")
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise VerifyError("tcp probe needs an integer port", code="invalid_probe")
    timeout = float(probe.get("timeout_seconds") or 5)
    t = max(1, int(timeout))
    script = (
        "if command -v python3 >/dev/null 2>&1; then "
        "python3 -c 'import socket,sys; "
        "socket.create_connection((sys.argv[1], int(sys.argv[2])), "
        f"timeout=float(sys.argv[3])).close()' {shell_quote(host)} {port} {t}; "
        "elif command -v bash >/dev/null 2>&1; then "
        f"bash -c 'exec 3<>/dev/tcp/{host}/{port}' 2>/dev/null; "
        "elif command -v nc >/dev/null 2>&1; then "
        f"nc -z -w {t} {shell_quote(host)} {port}; "
        "else echo tooling_missing; exit 3; fi"
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", script],
        job_id=job_id,
        settings=settings,
        timeout=timeout + 20,
    )
    name = probe.get("name") or f"tcp:{host}:{port}"
    if result.exit_code == 3 or "tooling_missing" in (result.stdout or ""):
        return {"ok": False, "probe": name, "type": "tcp", "error": "tooling_missing"}
    return {
        "ok": result.exit_code == 0,
        "probe": name,
        "type": "tcp",
        "host": host,
        "port": port,
        "exit_code": result.exit_code,
    }


def probe_command(
    environment_id: str,
    probe: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Pass: exit code == ``expect_exit`` (default 0) and, if set, stdout has the substring."""
    spec = probe.get("command")
    if not isinstance(spec, dict):
        raise VerifyError("command probe needs a command spec", code="invalid_probe")
    expect = int(probe.get("expect_exit", 0))
    contains = str(probe.get("stdout_contains") or "")
    timeout = float(probe.get("timeout_seconds") or spec.get("timeout_seconds") or 30)
    result = exec_command(
        environment_id,
        ["sh", "-lc", _spec_to_shell(spec, default_cwd=workdir or GUEST_REPO_ROOT)],
        job_id=job_id,
        settings=settings,
        timeout=timeout,
    )
    stdout = result.stdout or ""
    ok = result.exit_code == expect and (not contains or contains in stdout)
    return {
        "ok": ok,
        "probe": probe.get("name") or "command",
        "type": "command",
        "exit_code": result.exit_code,
        "expect_exit": expect,
        "stdout_contains": contains or None,
        "stdout_tail": stdout[-300:],
        "stderr_tail": (result.stderr or "")[-300:],
    }


def run_probe(
    environment_id: str,
    probe: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    workdir: str | None = None,
    default_retries: int = 1,
) -> dict[str, Any]:
    """Run one declared probe, retrying ``retries`` times ``interval_seconds`` apart."""
    kind = probe_type(probe)
    retries = max(int(probe.get("retries") or default_retries), 1)
    interval = float(probe.get("interval_seconds", 1))
    result: dict[str, Any] = {}
    attempts = 0
    for attempts in range(1, retries + 1):
        if kind == "http":
            result = probe_http(environment_id, probe, job_id=job_id, settings=settings)
        elif kind == "tcp":
            result = probe_tcp(environment_id, probe, job_id=job_id, settings=settings)
        elif kind == "command":
            result = probe_command(
                environment_id, probe, job_id=job_id, settings=settings, workdir=workdir
            )
        else:
            raise VerifyError(f"unsupported probe type {kind!r}", code="invalid_probe")
        if result.get("ok") or result.get("error") == "tooling_missing":
            break
        if attempts < retries and interval > 0:
            time.sleep(interval)
    result["attempts"] = attempts
    _log(
        job_id,
        f"probe {result.get('probe')} ({kind}) → {'ok' if result.get('ok') else 'FAILED'}",
        settings=settings,
        kind="probe",
        probe_result={k: v for k, v in result.items() if k != "log_snip"},
    )
    return result


# --- services / process stack ------------------------------------------------------------


def start_services(
    environment_id: str,
    profile: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    handles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Start declared services in ``depends_on`` order; each must pass its checks first.

    A service is up when every declared port accepts TCP and its ``healthcheck`` passes.
    A failed required service raises ``service_failed``; a failed ``optional`` one is logged
    and its (optional) dependents are skipped.
    """
    workdir = str(profile.get("workdir") or GUEST_REPO_ROOT)
    results: list[dict[str, Any]] = []
    failed: set[str] = set()
    for svc in service_launch_order(list(profile.get("services") or [])):
        name = str(svc["name"])
        optional = bool(svc.get("optional"))
        entry: dict[str, Any] = {"service": name, "kind": svc.get("kind"), "optional": optional}
        bad_dep = next((d for d in svc.get("depends_on") or [] if d in failed), None)
        try:
            if bad_dep:
                raise VerifyError(
                    f"service {name} skipped: dependency {bad_dep} failed",
                    code="service_failed",
                )
            handle = launch_supervised_process(
                environment_id,
                {
                    "name": f"svc-{name}",
                    "command": svc["command"],
                    "supervise": svc.get("supervise", "restart"),
                    "stop_signal": svc.get("stop_signal"),
                    "max_restarts": svc.get("max_restarts", DEFAULT_MAX_RESTARTS),
                    "ready_after_seconds": 0,
                },
                job_id=job_id,
                settings=settings,
                default_cwd=workdir,
                extra_env=dict(svc.get("env") or {}),
            )
            handles.append(handle)
            checks = [
                run_probe(
                    environment_id,
                    {"type": "tcp", "port": port, "name": f"{name}:{port}", **SERVICE_PORT_WAIT},
                    job_id=job_id,
                    settings=settings,
                )
                for port in svc["ports"]
            ]
            checks.append(
                run_probe(
                    environment_id,
                    {"name": f"{name}:healthcheck", **svc["healthcheck"]},
                    job_id=job_id,
                    settings=settings,
                    workdir=workdir,
                )
            )
            entry["checks"] = checks
            if not all(c.get("ok") for c in checks):
                raise VerifyError(f"service {name} failed its health check", code="service_failed")
            entry["ok"] = True
        except VerifyError as exc:
            entry.update(ok=False, error=exc.message)
            failed.add(name)
            _log(
                job_id,
                f"service {name} {'(optional) ' if optional else ''}FAILED: {exc.message}",
                settings=settings,
                kind="service",
                service=name,
                optional=optional,
                code=exc.code,
            )
            if not optional:
                results.append(entry)
                raise VerifyError(
                    exc.message, code="service_failed" if exc.code != "launch_failed" else exc.code
                ) from exc
        results.append(entry)
    return results


def _launch_stack(
    environment_id: str,
    profile: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    handles: list[dict[str, Any]],
) -> dict[str, Any]:
    """Services (dependency order), then processes (each gated by its ready_probe), PORT env."""
    workdir = str(profile.get("workdir") or GUEST_REPO_ROOT)
    ports = [int(p) for p in profile.get("ports") or []]
    detail: dict[str, Any] = {}
    detail["services"] = start_services(
        environment_id, profile, job_id=job_id, settings=settings, handles=handles
    )
    named = {p["name"]: p for p in profile_probes(profile) if p.get("name")}
    # PORT defaults to the first declared port (webapp/demo fall back to 5000).
    if ports:
        extra_env = {"PORT": str(ports[0])}
    else:
        extra_env = {} if profile.get("intent") == "git_mcp" else {"PORT": "5000"}
    launched: list[dict[str, Any]] = []
    for proc in effective_processes(profile):
        handle = launch_supervised_process(
            environment_id,
            proc,
            job_id=job_id,
            settings=settings,
            default_cwd=workdir,
            extra_env=extra_env,
        )
        handles.append(handle)
        launched.append({k: v for k, v in handle.items() if k != "log_path"})
        ref = proc.get("ready_probe")
        if ref:
            gate = run_probe(
                environment_id,
                {"retries": 15, **named[ref]},
                job_id=job_id,
                settings=settings,
                workdir=workdir,
            )
            launched[-1]["ready_probe"] = gate
            if not gate.get("ok"):
                raise VerifyError(
                    f"process {proc['name']} not ready: probe {ref} failed",
                    code="process_not_ready",
                )
    detail["processes"] = launched
    if ports and launched:
        # Best-effort wait for the first declared port before the real probes.
        run_probe(
            environment_id,
            {"type": "tcp", "port": ports[0], "retries": 15, "timeout_seconds": 2},
            job_id=job_id,
            settings=settings,
        )
    return detail


def verify_mcp_stdio(
    environment_id: str,
    profile: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    mcp = profile.get("mcp") or {}
    launch = mcp.get("launch_command")
    if not isinstance(launch, dict):
        raise VerifyError("mcp.launch_command required for stdio", code="invalid_mcp")
    readiness = mcp.get("readiness") or {}
    timeout = float(readiness.get("timeout_seconds") or launch.get("timeout_seconds") or 30)
    workdir = str(profile.get("workdir") or GUEST_REPO_ROOT)
    cwd = resolve_guest_path(str(launch.get("cwd") or mcp.get("cwd") or workdir), workdir)
    if launch.get("argv"):
        launch_argv = [str(x) for x in launch["argv"]]
    elif launch.get("shell"):
        launch_argv = ["sh", "-lc", str(launch["shell"])]
    else:
        raise VerifyError("mcp.launch_command needs argv or shell", code="invalid_mcp")

    helper = f"{GUEST_HELPERS}/mcp_stdio_verify.py"
    # Refresh helper after offline snap so host-side fixes apply (D60/D63).
    copy_in(
        environment_id,
        "mcp_stdio_verify",
        helper,
        job_id=job_id,
        settings=settings,
    )
    # Run helper with cwd applied so relative launch bins resolve (D62 checkout).
    # launch_command.env is exported here so the helper's server subprocess inherits it (P2).
    cmd = (
        f"cd {_shell_quote(cwd)} || exit 1; {env_exports(launch.get('env'))}"
        f"python3 {_shell_quote(helper)} --timeout {int(timeout)} -- "
        + " ".join(_shell_quote(a) for a in launch_argv)
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", cmd],
        job_id=job_id,
        settings=settings,
        timeout=timeout + 60,
    )
    evidence: dict[str, Any] = {}
    raw = (result.stdout or "").strip().splitlines()
    for line in reversed(raw):
        line = line.strip()
        if line.startswith("{"):
            try:
                evidence = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    ok = result.exit_code == 0 and bool(evidence.get("ok"))
    detail = {
        "ok": ok,
        "type": "mcp_handshake",
        "transport": "stdio",
        "exit_code": result.exit_code,
        "evidence": evidence,
        "stderr": (result.stderr or "")[:400],
    }
    _log(
        job_id,
        f"mcp_stdio_verify → {'ok' if ok else 'FAILED'}",
        settings=settings,
        kind="mcp_stdio_verify",
        **{k: v for k, v in detail.items() if k != "stderr"},
    )
    return detail


def verify_mcp_streamable_http(
    environment_id: str,
    profile: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    """HTTP MCP: process must be up; probe URL must respond (list-tools best-effort)."""
    mcp = profile.get("mcp") or {}
    url = str(mcp.get("url") or "").strip()
    if not url:
        raise VerifyError("mcp.url required for streamable_http", code="invalid_mcp")
    # Ensure process launched first by caller.
    http = probe_http(
        environment_id,
        {
            "name": "mcp-http",
            "type": "http",
            "url": url,
            "accept": [200, 201, 204],
            "timeout_seconds": (mcp.get("readiness") or {}).get("timeout_seconds") or 15,
        },
        job_id=job_id,
        settings=settings,
    )
    # Without a full HTTP MCP client in-guest, require HTTP success + note limitation.
    # D30 still demands list-tools; attempt a JSON-RPC POST if curl is present.
    list_tools = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            (
                f"curl -sS -o /tmp/killhub-mcp-http.out -w '%{{http_code}}' "
                f"-H 'Content-Type: application/json' "
                f'-d \'{{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{{}}}}\' '
                f"{_shell_quote(url)} || true"
            ),
        ],
        job_id=job_id,
        settings=settings,
        timeout=30,
    )
    body = ""
    try:
        body_result = exec_command(
            environment_id,
            ["sh", "-lc", "cat /tmp/killhub-mcp-http.out 2>/dev/null | head -c 2000"],
            job_id=job_id,
            settings=settings,
            timeout=15,
        )
        body = body_result.stdout or ""
    except Exception:  # noqa: BLE001
        body = ""
    tools_ok = False
    tool_names: list[str] = []
    try:
        parsed = json.loads(body) if body.strip().startswith("{") else {}
        tools = ((parsed.get("result") or {}).get("tools")) or []
        if isinstance(tools, list) and len(tools) >= 1:
            tools_ok = True
            tool_names = [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
    except json.JSONDecodeError:
        tools_ok = False
    ok = bool(http.get("ok")) and tools_ok
    return {
        "ok": ok,
        "type": "mcp_handshake",
        "transport": "streamable_http",
        "http": http,
        "tool_names": tool_names,
        "list_tools_http": (list_tools.stdout or "").strip()[:20],
    }


def _verification_for_outcome(
    profile: dict[str, Any],
    *,
    passed: bool,
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    target = str(profile.get("verification_target") or "original_application")
    if not passed:
        # Keep prior setup_failed if already set (fixture path).
        if existing and existing.get("kind") == "setup_failed":
            return dict(existing)
        return {
            "kind": "setup_failed",
            "original_failure": {
                "step": "verify",
                "summary": "readiness probe did not pass",
            },
        }
    if target == "generated_demo":
        original_failure = None
        if existing and existing.get("original_failure"):
            original_failure = existing["original_failure"]
        elif profile.get("original_failure"):
            original_failure = profile["original_failure"]
        else:
            original_failure = {
                "step": "discover",
                "summary": "generated demo; original application path not claimed",
            }
        return {"kind": "generated_demo", "original_failure": original_failure}
    return {"kind": "original_application"}


def _collect_launch_logs(environment_id: str, *, job_id: str, settings: Settings) -> str:
    try:
        res = exec_command(
            environment_id,
            ["sh", "-lc", "tail -c 2500 /tmp/killhub/*.log 2>/dev/null || true"],
            job_id=job_id,
            settings=settings,
            timeout=20,
        )
        return (res.stdout or "")[-2500:]
    except Exception:  # noqa: BLE001 - evidence only
        return ""


def _repair_verify_plan(
    job_id: str,
    profile: dict[str, Any],
    last_detail: dict[str, Any],
    *,
    environment_id: str,
    attempt: int,
    max_attempts: int,
    settings: Settings,
) -> tuple[dict[str, Any], int | None]:
    """Revise launch/probe plan from a real readiness failure (D85); offline-safe fields only.

    The verify phase has no network, so packages/install/intent are locked in
    plan_llm. Returns (profile, revision) with revision None when unchanged.
    """
    from agent import AgentError, EnvironmentAgent
    from plan_llm import TrustedFacts

    job = get_ledger(settings).get_job(job_id)
    if job is None or not job.resolved_commit:
        return profile, None
    try:
        agent = EnvironmentAgent(job_id, settings=settings)
    except (AgentError, ValueError, OSError):
        return profile, None
    source = profile.get("source") or {}
    facts = TrustedFacts(
        git_url=str(source.get("url") or job.git_url),
        commit=job.resolved_commit,
        ref=str(source.get("ref") or "HEAD"),
        oci_image=str(profile.get("oci_image") or settings.msb_default_image or "debian"),
    )
    # Only spend a guest exec on log evidence when the planner can actually use it.
    logs = (
        _collect_launch_logs(environment_id, job_id=job_id, settings=settings)
        if agent.inference_available()[0]
        else ""
    )
    detail_text = json.dumps(last_detail, default=str)[:2500]
    proposal = agent.revise_runtime_profile(
        facts=facts,
        profile=profile,
        phase="verify",
        attempt=attempt,
        max_attempts=max_attempts,
        failures=[
            {
                "name": "readiness_probe",
                "exit_code": last_detail.get("exit_code"),
                "output_tail": detail_text[-600:],
            }
        ],
        evidence=f"probe result:\n{detail_text}\n\nprocess logs:\n{logs}",
        expires_at=job.expires_at,
    )
    if proposal is None or not proposal.changed:
        return profile, None
    try:
        rev = persist_profile_revision(job_id, proposal.profile, phase="runtime", settings=settings)
    except ProfileError as exc:
        _log(
            job_id,
            f"verify repair revision rejected: {exc.message}",
            settings=settings,
            kind="plan_llm",
        )
        return profile, None
    _log(
        job_id,
        f"verify plan revised (profile revision {rev.revision}): {proposal.rationale}"[:300],
        settings=settings,
        kind="repair",
        attempt=attempt,
        revision=rev.revision,
        changes=proposal.changes,
        rationale=proposal.rationale,
    )
    return proposal.profile, rev.revision


def verify_readiness(
    job_id: str,
    *,
    settings: Settings | None = None,
) -> VerifyResult:
    """
    Launch (if needed) + probe → set readiness + verification.kind (D37, D54).

    Does not set status=completed and does not destroy Plane 2.
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise VerifyError(f"unknown job_id: {job_id}", code="not_found")

    # Fixture setup_failed may already be terminal with verification set and no
    # runtime profile - honour it without inventing a demo (D53, D54).
    if job.verification and job.verification.get("kind") == "setup_failed":
        return VerifyResult(
            job_id=job_id,
            environment_id=job.sandbox_id or "",
            passed=False,
            verification_kind="setup_failed",
            readiness=job.readiness,
            verification=job.verification,
            verify_result={"skipped": True, "reason": "setup_failed"},
            destroyed=job.destroyed_at is not None,
            completed=job.status == "completed",
        )

    if not job.sandbox_id:
        raise VerifyError("no live sandbox for verify", code="no_sandbox")
    environment_id = job.sandbox_id
    profile = _current_runtime_profile(job_id, cfg)
    assert_built_checkout_launch(profile, resolved_commit=job.resolved_commit)

    _status(
        job_id,
        "verifying",
        settings=cfg,
        step="launch + readiness probe",
        progress=max(job.progress, 85),
    )

    intent = profile.get("intent")
    max_attempts = max(int(cfg.max_repair_attempts or 1), 1)
    last_detail: dict[str, Any] = {}
    passed = False
    probe_name = "unknown"
    plan_revisions: list[int] = []

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            # Job deadline is checked on every repair iteration (D41, D83).
            fresh = ledger.get_job(job_id)
            if fresh is not None and deadline_exceeded(fresh.expires_at):
                last_detail = {
                    "ok": False,
                    "error": "job expires_at reached before verify repair attempt",
                    "code": "deadline_exceeded",
                }
                passed = False
                _log(
                    job_id,
                    "verify repair stopped: job deadline reached",
                    settings=cfg,
                    kind="verify",
                    code="deadline_exceeded",
                )
                break
            _status(
                job_id,
                "repairing",
                settings=cfg,
                step=f"verify repair attempt {attempt}",
                progress=max(job.progress, 86),
            )
            _log(
                job_id,
                f"verify repair attempt {attempt}",
                settings=cfg,
                kind="repair",
                attempt=attempt,
            )
            profile, revision = _repair_verify_plan(
                job_id,
                profile,
                last_detail,
                environment_id=environment_id,
                attempt=attempt,
                max_attempts=max_attempts,
                settings=cfg,
            )
            if revision is not None:
                plan_revisions.append(revision)
                intent = profile.get("intent")

        handles: list[dict[str, Any]] = []
        try:
            stack = _launch_stack(
                environment_id, profile, job_id=job_id, settings=cfg, handles=handles
            )
            workdir = str(profile.get("workdir") or GUEST_REPO_ROOT)
            if intent == "git_mcp":
                mcp = profile.get("mcp") or {}
                # stdio: the helper owns the subprocess lifetime (no profile processes).
                # streamable_http: the stack above started the server; handshake it.
                if mcp.get("transport") == "streamable_http":
                    last_detail = verify_mcp_streamable_http(
                        environment_id, profile, job_id=job_id, settings=cfg
                    )
                    probe_name = "mcp_handshake_http"
                else:
                    last_detail = verify_mcp_stdio(
                        environment_id, profile, job_id=job_id, settings=cfg
                    )
                    probe_name = "mcp_handshake_stdio"
                passed = bool(last_detail.get("ok"))
                extra = profile_probes(profile)
                if passed and extra:
                    results = [
                        run_probe(environment_id, p, job_id=job_id, settings=cfg, workdir=workdir)
                        for p in extra
                    ]
                    passed = all(r.get("ok") for r in results)
                    last_detail = {**last_detail, "ok": passed, "probes": results}
            else:
                # webapp / demo: every declared probe (http | tcp | command) must pass.
                probes = profile_probes(profile)
                if not probes:
                    raise VerifyError(
                        f"{intent} profile requires probes",
                        code="missing_probes",
                    )
                results = [
                    run_probe(environment_id, p, job_id=job_id, settings=cfg, workdir=workdir)
                    for p in probes
                ]
                passed = all(r.get("ok") for r in results)
                probe_name = str(
                    probes[0].get("name") or probes[0].get("url") or probe_type(probes[0])
                )
                last_detail = {"ok": passed, "type": "probes", "probes": results}
            if stack.get("services") or stack.get("processes"):
                last_detail = {**last_detail, **stack}
        except VerifyError as exc:
            last_detail = {"ok": False, "error": exc.message, "code": exc.code}
            passed = False
            _log(
                job_id,
                f"verify attempt {attempt} error: {exc.message}",
                settings=cfg,
                kind="verify",
                code=exc.code,
            )

        if passed:
            break
        # Cleanup: a failed attempt must not leave its services/processes holding ports
        # for the relaunch (or the finalizer). A passing stack stays up for stills/scans.
        stop_all(environment_id, handles, job_id=job_id, settings=cfg)

    if plan_revisions:
        last_detail = {**last_detail, "plan_revisions": plan_revisions}
    verification = _verification_for_outcome(profile, passed=passed, existing=job.verification)
    readiness: dict[str, Any] | None
    if passed:
        readiness = {
            "passed": True,
            "probe": probe_name,
            "detail": last_detail,
            "at": utc_now(),
        }
    else:
        readiness = {
            "passed": False,
            "probe": probe_name,
            "detail": last_detail,
            "at": utc_now(),
        }

    # Persist evidence only - never completed, never destroy (D37).
    # Failed readiness stays non-terminal so the finalizer owns SCA + destroy +
    # terminal status (D37, D53, D61). Discover already follows this pattern.
    new_status = "verifying"
    _log(
        job_id,
        f"readiness passed={passed} kind={verification.get('kind')}",
        settings=cfg,
        kind="verify",
        readiness=readiness,
        verification=verification,
    )
    job_fields = {
        "current_step": "readiness passed" if passed else "readiness failed - awaiting finalize",
        "progress": 90,
        "readiness": readiness,
        "verification": verification,
        "verify_result": last_detail,
    }
    event_payload = {
        "readiness_passed": passed,
        "verification_kind": verification.get("kind"),
    }
    ledger.append_event(
        job_id,
        typ="status",
        message=new_status,
        payload={"status": new_status, **event_payload},
    )
    ledger.update_job_fields(job_id, status=new_status, **job_fields)

    # Confirm sandbox still present (not destroyed by this step).
    job_after = ledger.get_job(job_id)
    return VerifyResult(
        job_id=job_id,
        environment_id=environment_id,
        passed=passed,
        verification_kind=str(verification.get("kind")),
        readiness=readiness,
        verification=verification,
        verify_result=last_detail,
        destroyed=bool(job_after and job_after.destroyed_at),
        completed=bool(job_after and job_after.status == "completed"),
    )
