"""Readiness verify + verification kinds (D30, D37, D47, D54, D62, D66).

Sets `readiness` / `verification` from real probes. Never marks `completed`
and never destroys the sandbox (D37).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from profile import GUEST_REPO_ROOT, assert_runtime_ready_for_provision
from typing import Any

from config import Settings, get_settings
from errors import HarnessError
from fixtures import match_fixture
from harness import copy_in, exec_command
from jobs import get_ledger
from ledger.store import utc_now
from models import Job

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


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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
    stored = runtime[-1].profile
    profile = assert_runtime_ready_for_provision(stored, stored=True)
    if profile.get("verification_target") == "generated_demo" and isinstance(
        stored.get("original_failure"), dict
    ):
        # Historical failure context is read for reporting only.
        return {**profile, "original_failure": stored["original_failure"]}
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

    commands = profile.get("commands")
    if commands is None:
        commands = {"run": profile.get("run_commands"), "install": profile.get("install_commands")}
    specs: list[dict[str, Any]] = []
    for key in ("run", "install"):
        for item in commands.get(key) or []:
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


def _spec_to_shell(spec: dict[str, Any], *, default_cwd: str) -> str:
    cwd = str(spec.get("cwd") or default_cwd)
    if spec.get("argv"):
        argv = [str(x) for x in spec["argv"]]
        return f"cd {_shell_quote(cwd)} && exec " + " ".join(_shell_quote(a) for a in argv)
    if spec.get("shell"):
        return f"cd {_shell_quote(cwd)} && {spec['shell']}"
    raise VerifyError("command spec missing argv/shell", code="invalid_command")


def launch_supervised_process(
    environment_id: str,
    process: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    default_cwd: str,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start a profile process in the guest background (verify-phase loopback)."""
    name = str(process.get("name") or "app")
    command = process.get("command")
    if not isinstance(command, dict):
        raise VerifyError(f"process {name} missing command", code="invalid_process")
    shell = _spec_to_shell(command, default_cwd=default_cwd)
    env_exports = ""
    for key, value in (extra_env or {}).items():
        env_exports += f"export {key}={_shell_quote(value)}; "
    log_path = f"/tmp/killhub/{name}.log"
    pid_path = f"/tmp/killhub/{name}.pid"
    script = (
        f"mkdir -p /tmp/killhub && "
        f"nohup sh -c {_shell_quote(env_exports + shell)} "
        f">{_shell_quote(log_path)} 2>&1 & "
        f"echo $! >{_shell_quote(pid_path)} && cat {_shell_quote(pid_path)}"
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
    delay = float(process.get("ready_after_seconds") or 1)
    if delay > 0:
        exec_command(
            environment_id,
            ["sh", "-lc", f"sleep {delay}"],
            job_id=job_id,
            settings=settings,
            timeout=delay + 15,
        )
    # Best-effort: wait until a declared port accepts connections.
    ports = []
    ready_probe = process.get("ready_probe")
    _log(
        job_id,
        f"launched process {name} pid={pid}",
        settings=settings,
        kind="verify",
        process=name,
        pid=pid,
        log_path=log_path,
        ready_probe=ready_probe,
        ports=ports,
    )
    return {"name": name, "pid": pid, "log_path": log_path}


def probe_http(
    environment_id: str,
    probe: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
) -> dict[str, Any]:
    url = str(probe.get("url") or "").strip()
    if not url:
        raise VerifyError("http probe missing url", code="invalid_probe")
    timeout = float(probe.get("timeout_seconds") or 10)
    accept = probe.get("expected_statuses", probe.get("accept")) or [200]
    accept_set = {int(x) for x in accept}
    # Prefer curl -w for a reliable status; wget as fallback.
    script = (
        f"URL={_shell_quote(url)}; "
        "if command -v curl >/dev/null 2>&1; then "
        f"code=$(curl -sS -o /tmp/killhub-http-probe.out -w '%{{http_code}}' "
        f'--max-time {int(timeout)} "$URL" || echo 000); '
        'echo "http_code:$code"; '
        "elif command -v wget >/dev/null 2>&1; then "
        f'wget -S -O /tmp/killhub-http-probe.out --timeout={int(timeout)} "$URL" '
        ">/tmp/killhub-http-probe.hdr 2>&1 || true; "
        "code=$(awk 'BEGIN{c=0} /HTTP\\//{c=$2} END{print c+0}' "
        "/tmp/killhub-http-probe.hdr); "
        'echo "http_code:$code"; '
        "else echo tooling_missing; exit 3; fi"
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
    ok = code is not None and code in accept_set
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
        "accept": sorted(accept_set),
        "exit_code": result.exit_code,
        "log_snip": log_snip,
    }


def verify_mcp_stdio(
    environment_id: str,
    profile: dict[str, Any],
    *,
    job_id: str,
    settings: Settings,
    final_inventory: bool = False,
) -> dict[str, Any]:
    mcp = profile.get("mcp") or {}
    launch = mcp.get("launch_command")
    if not isinstance(launch, dict):
        raise VerifyError("mcp.launch_command required for stdio", code="invalid_mcp")
    readiness = mcp.get("readiness") or {}
    timeout = float(readiness.get("timeout_seconds") or launch.get("timeout_seconds") or 30)
    cwd = str(launch.get("cwd") or mcp.get("cwd") or profile.get("workdir") or GUEST_REPO_ROOT)
    if launch.get("argv"):
        launch_argv = [str(x) for x in launch["argv"]]
    elif launch.get("shell"):
        launch_argv = ["sh", "-lc", str(launch["shell"])]
    else:
        raise VerifyError("mcp.launch_command needs argv or shell", code="invalid_mcp")

    # Extra read-only collection is limited to the trusted fixture at its exact pin.
    source = profile.get("source") or {}
    fixture = match_fixture(str(source.get("url") or ""))
    job = get_ledger(settings).get_job(job_id) if fixture else None
    inventory = bool(
        fixture
        and fixture.get("id") == "git_mcp_filesystem"
        and job
        and job.sandbox_id == environment_id
        and job.current_sandbox_generation is not None
        and job.resolved_commit == source.get("commit")
        and source.get("commit") == fixture.get("commit")
    )
    if final_inventory and not inventory:
        raise VerifyError("Final inventory requires the pinned fixture VM")
    inventory_option = " --inventory" if inventory else ""
    helper = f"{GUEST_HELPERS}/mcp_stdio_verify.py"
    # Refresh helper after offline snap so host-side fixes apply (D60/D63).
    if final_inventory:
        # The baseline installed this helper in the same generation.
        timeout = min(timeout, 5)
    else:
        copy_in(
            environment_id,
            "mcp_stdio_verify",
            helper,
            job_id=job_id,
            settings=settings,
        )
    # Run helper with cwd applied so relative launch bins resolve (D62 checkout).
    cmd = (
        f"cd {_shell_quote(cwd)} && "
        f"python3 {_shell_quote(helper)} --timeout {int(timeout)}{inventory_option} -- "
        + " ".join(_shell_quote(a) for a in launch_argv)
    )
    result = exec_command(
        environment_id,
        ["sh", "-lc", cmd],
        job_id=job_id,
        settings=settings,
        timeout=22 if final_inventory else timeout + 60,
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
    if not inventory:
        evidence.pop("inventory", None)
    detail = {
        "ok": ok,
        "type": "mcp_handshake",
        "transport": "stdio",
        "exit_code": result.exit_code,
        "evidence": evidence,
        "stderr": (result.stderr or "")[:400],
    }
    if inventory and job is not None:
        # Scope is assigned by the worker, never by the guest's JSON result.
        detail["inventory_scope"] = {
            "generation": job.current_sandbox_generation,
            "commit": job.resolved_commit,
            "profile_revision": job.current_profile_revision,
        }
    _log(
        job_id,
        f"mcp_stdio_verify → {'ok' if ok else 'FAILED'}",
        settings=settings,
        kind="mcp_stdio_verify",
        **{k: v for k, v in detail.items() if k != "stderr"},
    )
    return detail


def compare_mcp_inventory(initial: dict, final: dict) -> dict:
    """Compare only complete lists. A missing or unsupported list proves no equality."""
    comparison = {}
    for collection in ("tools", "resources", "prompts"):
        before = initial.get(collection)
        after = final.get(collection)
        if not all(
            isinstance(record, dict)
            and record.get("status") == "recorded"
            and isinstance(record.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
            and type(record.get("count")) is int
            and 0 <= record["count"] <= 256
            for record in (before, after)
        ):
            comparison[collection] = {"status": "unavailable"}
            continue
        comparison[collection] = {
            "status": "unchanged" if before["sha256"] == after["sha256"] else "changed",
            "initial": {key: before[key] for key in ("count", "sha256")},
            "final": {key: after[key] for key in ("count", "sha256")},
        }
    return comparison


def compare_fixture_inventory(job: Job, settings: Settings) -> dict | None:
    """Take the final observation for a ready fixture and report partial evidence safely."""
    readiness = job.readiness or {}
    detail = readiness.get("detail") or {}
    initial = (detail.get("evidence") or {}).get("inventory")
    scope = detail.get("inventory_scope")
    fixture = match_fixture(job.github_url)
    if not (
        readiness.get("passed")
        and isinstance(initial, dict)
        and isinstance(scope, dict)
        and fixture
        and fixture.get("id") == "git_mcp_filesystem"
        and fixture.get("commit") == job.resolved_commit
    ):
        return None
    final: dict = {}
    if (
        job.sandbox_id
        and not job.cancel_requested_at
        and job.expires_at > utc_now()
        and scope
        == {
            "generation": job.current_sandbox_generation,
            "commit": job.resolved_commit,
            "profile_revision": job.current_profile_revision,
        }
    ):
        try:
            profile = _current_runtime_profile(job.job_id, settings)
            observation = verify_mcp_stdio(
                job.sandbox_id, profile, job_id=job.job_id, settings=settings, final_inventory=True
            )
        except (VerifyError, HarnessError, ValueError, OSError):
            # Expiry, replacement or a missing helper must not hold up teardown.
            observation = {}
        latest = get_ledger(settings).get_job(job.job_id)
        if (
            latest
            and not latest.cancel_requested_at
            and latest.sandbox_id == job.sandbox_id
            and latest.current_sandbox_generation == job.current_sandbox_generation
            and latest.current_profile_revision == job.current_profile_revision
            and observation.get("ok")
            and observation.get("inventory_scope") == scope
        ):
            value = (observation.get("evidence") or {}).get("inventory")
            if isinstance(value, dict):
                final = value
    return {"scope": scope, "collections": compare_mcp_inventory(initial, final)}


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


def _select_http_probes(profile: dict[str, Any]) -> list[dict[str, Any]]:
    probes = profile.get("probes") or profile.get("healthcheck") or []
    if isinstance(probes, dict):
        probes = [probes]
    out: list[dict[str, Any]] = []
    for p in probes:
        if isinstance(p, dict) and p.get("type") in {None, "http"} and p.get("url"):
            out.append(p)
    return out


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
                "summary": profile.get("summary")
                or "generated demo; original application unverified",
            }
        return {"kind": "generated_demo", "original_failure": original_failure}
    return {"kind": "original_application"}


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
    # runtime profile — honour it without inventing a demo (D53, D54).
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

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
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

        try:
            if intent == "git_mcp":
                mcp = profile.get("mcp") or {}
                transport = mcp.get("transport")
                # Launch long-running process only for HTTP transport; stdio
                # helper owns the subprocess lifetime.
                if transport == "streamable_http":
                    for proc in profile.get("processes") or []:
                        if isinstance(proc, dict):
                            launch_supervised_process(
                                environment_id,
                                proc,
                                job_id=job_id,
                                settings=cfg,
                                default_cwd=str(profile.get("workdir") or GUEST_REPO_ROOT),
                            )
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
            else:
                # webapp / demo — launch processes then HTTP probes.
                ports = [int(p) for p in (profile.get("ports") or []) if str(p).isdigit()]
                extra_env = {"PORT": str(ports[0])} if ports else {"PORT": "5000"}
                for proc in profile.get("processes") or []:
                    if isinstance(proc, dict):
                        launch_supervised_process(
                            environment_id,
                            proc,
                            job_id=job_id,
                            settings=cfg,
                            default_cwd=str(profile.get("workdir") or GUEST_REPO_ROOT),
                            extra_env=extra_env,
                        )
                # Poll briefly for listen readiness before first HTTP probe.
                if ports:
                    port = ports[0]
                    exec_command(
                        environment_id,
                        [
                            "sh",
                            "-lc",
                            (
                                f"for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do "
                                f"if command -v curl >/dev/null 2>&1; then "
                                f"curl -sf --max-time 1 http://127.0.0.1:{port}/ >/dev/null "
                                f"&& exit 0; "
                                f"elif command -v wget >/dev/null 2>&1; then "
                                f"wget -qO- --timeout=1 http://127.0.0.1:{port}/ >/dev/null "
                                f"&& exit 0; "
                                f"fi; sleep 1; done; exit 0"
                            ),
                        ],
                        job_id=job_id,
                        settings=cfg,
                        timeout=45,
                    )
                probes = _select_http_probes(profile)
                if not probes:
                    raise VerifyError(
                        f"{intent} profile requires HTTP probes",
                        code="missing_probes",
                    )
                results = [
                    probe_http(environment_id, p, job_id=job_id, settings=cfg) for p in probes
                ]
                passed = all(r.get("ok") for r in results)
                probe_name = str(probes[0].get("name") or probes[0].get("url") or "http")
                last_detail = {"ok": passed, "type": "http", "probes": results}
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

    # Persist — never completed, never destroy (D37).
    # Emit evidence while still non-terminal, then flip status (D61 freeze).
    new_status = "verifying" if passed else "failed"
    _log(
        job_id,
        f"readiness passed={passed} kind={verification.get('kind')}",
        settings=cfg,
        kind="verify",
        readiness=readiness,
        verification=verification,
    )
    job_fields = {
        "current_step": "readiness passed" if passed else "readiness failed",
        "progress": 90 if passed else 100,
        "readiness": readiness,
        "verification": verification,
        "verify_result": last_detail,
    }
    event_payload = {
        "readiness_passed": passed,
        "verification_kind": verification.get("kind"),
    }
    if passed:
        ledger.append_event(
            job_id,
            typ="status",
            message=new_status,
            payload={"status": new_status, **event_payload},
        )
        ledger.update_job_fields(job_id, status=new_status, **job_fields)
    else:
        # Failed readiness is terminal: receipt + status event + status atomically (D61).
        ledger.finalize_job(
            job_id,
            status="failed",
            # A failed readiness probe still yields an explicitly incomplete verdict.
            include_verdict=True,
            receipt={
                "verification": verification,
                "dossier": {"outcome": "setup_failed", "readiness": readiness},
            },
            event_message=new_status,
            event_payload=event_payload,
            **job_fields,
        )

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
