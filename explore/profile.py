"""environment_profile.json schema + bootstrap/runtime IO (D51, D36, D64)."""

from __future__ import annotations

import json
import posixpath
import re
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from errors import HarnessError
from jobs import get_ledger
from models import ProfilePhase

SCHEMA_VERSION = "1"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "environment_profile.v1.json"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

RUNTIME_INTENTS = frozenset({"git_mcp", "webapp", "demo"})
GUEST_REPO_ROOT = "/tmp/killhub/repo"

# --- supported executable contract (P2: accepted fields are honored or rejected) ---------
SUPERVISE_MODES = frozenset({"oneshot", "restart"})
STOP_SIGNALS = frozenset({"SIGTERM", "SIGINT", "SIGHUP", "SIGQUIT", "SIGKILL"})
PROBE_TYPES = frozenset({"http", "tcp", "command"})
DEFAULT_MAX_RESTARTS = 3

# Killhub secrets and loader/shell hijack variables never enter the guest via profile env.
_ENV_DENY_PREFIXES = ("VULTR_", "OPENCODE_", "KILLHUB_", "MSB_", "KH_", "LD_", "DYLD_")
_ENV_DENY_NAMES = frozenset({"BASH_ENV", "ENV", "IFS", "SHELLOPTS", "PS4"})
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_HOST_RE = re.compile(r"^[A-Za-z0-9_.:\[\]-]{1,253}$")
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9+_.:@/=~-]*$")

TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "intent",
        "source",
        "runtime",
        "os_image",
        "oci_image",
        "workdir",
        "services",
        "packages",
        "install_commands",
        "run_commands",
        "processes",
        "ports",
        "summary",
        "verification_target",
        "mcp",
        "probes",
        "healthcheck",
        "original_failure",
    }
)
COMMAND_KEYS = frozenset({"argv", "shell", "cwd", "env", "timeout_seconds", "killhub_tooling"})
_SUPERVISION = frozenset({"supervise", "stop_signal", "max_restarts"})
_PROCESS_KEYS = frozenset({"name", "command", "ready_after_seconds", "ready_probe"}) | _SUPERVISION
_SERVICE_KEYS = (
    frozenset({"name", "kind", "package", "command", "ports", "env", "healthcheck"})
    | frozenset({"depends_on", "optional"})
    | _SUPERVISION
)
_PROBE_COMMON_KEYS = frozenset({"name", "type", "timeout_seconds", "retries", "interval_seconds"})
_PROBE_TYPE_KEYS = {
    "http": frozenset({"url", "accept", "body_contains"}),
    "tcp": frozenset({"host", "port"}),
    "command": frozenset({"command", "expect_exit", "stdout_contains"}),
}
_MCP_KEYS = frozenset(
    {
        "transport",
        "launch_command",
        "cwd",
        "entrypoint",
        "url",
        "readiness",
        "security_assessment",
    }
)
_MCP_READINESS_KEYS = frozenset({"type", "transport", "timeout_seconds"})


class ProfileError(Exception):
    def __init__(self, message: str, *, code: str = "profile_invalid") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def profiles_root(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    root = Path(cfg.profile_storage)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent / root
    return root.resolve()


def bootstrap_profile(
    *,
    github_url: str,
    oci_image: str,
    ref: str | None = None,
) -> dict[str, Any]:
    """Killhub-owned bootstrap profile - clone-only, no install/run (D36)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "intent": "bootstrap",
        "source": {
            "type": "git",
            "url": github_url,
            "ref": ref or "HEAD",
        },
        "runtime": "bootstrap",
        "os_image": "linux",
        "oci_image": oci_image,
        "workdir": GUEST_REPO_ROOT,
        "services": [],
        "packages": [],
        "install_commands": [],
        "run_commands": [],
        "processes": [],
        "ports": [],
        "summary": "Trusted bootstrap sandbox for inspect-only clone (D36)",
        "verification_target": "original_application",
    }


def _require(obj: dict[str, Any], key: str, *, ctx: str) -> Any:
    if key not in obj:
        raise ProfileError(f"{ctx}: missing required field '{key}'")
    return obj[key]


def _unsupported(message: str) -> ProfileError:
    """A field or mode the harness does not execute: rejected before provision."""
    return ProfileError(message, code="profile_unsupported")


def _reject_unknown(obj: dict[str, Any], allowed: frozenset[str], *, ctx: str) -> None:
    extra = sorted(str(k) for k in obj if k not in allowed)
    if extra:
        raise _unsupported(
            f"{ctx}: unsupported field(s) {', '.join(extra)} "
            f"(supported: {', '.join(sorted(allowed))})"
        )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_name(value: Any, *, ctx: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.match(value):
        raise ProfileError(f"{ctx}: name must match {_NAME_RE.pattern}")
    return value


def _check_number(
    value: Any, *, ctx: str, low: float, high: float, allow_low: bool = False
) -> None:
    if not _is_number(value) or value > high or (value < low if allow_low else value <= low):
        op = ">=" if allow_low else ">"
        raise ProfileError(f"{ctx} must be a number {op} {low:g} and <= {high:g}")


def validate_command_env(env: Any, *, ctx: str) -> dict[str, str]:
    """Permitted command environment: string map, no Killhub secrets or loader hijacks."""
    if env is None:
        return {}
    if not isinstance(env, dict):
        raise ProfileError(f"{ctx}.env must be an object")
    for key, value in env.items():
        if not isinstance(key, str) or not _ENV_KEY_RE.match(key):
            raise ProfileError(f"{ctx}.env: invalid variable name {key!r}")
        if not isinstance(value, str) or "\x00" in value:
            raise ProfileError(f"{ctx}.env.{key} must be a string")
        upper = key.upper()
        if upper.startswith(_ENV_DENY_PREFIXES) or upper in _ENV_DENY_NAMES:
            raise _unsupported(
                f"{ctx}.env.{key} is not a permitted environment variable "
                "(Killhub secrets and loader overrides never enter the sandbox)"
            )
    return dict(env)


def _validate_command_spec(
    spec: Any, *, ctx: str, extra_keys: frozenset[str] = frozenset()
) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise ProfileError(f"{ctx} must be an object")
    _reject_unknown(spec, COMMAND_KEYS | extra_keys, ctx=ctx)
    has_argv, has_shell = "argv" in spec, "shell" in spec
    if not has_argv and not has_shell:
        raise ProfileError(f"{ctx} requires argv or shell")
    if has_argv and has_shell:
        raise ProfileError(f"{ctx} must set exactly one of argv or shell")
    if has_argv:
        argv = spec["argv"]
        if (
            not isinstance(argv, list)
            or not argv
            or not all(isinstance(a, str) for a in argv)
            or not argv[0]
        ):
            raise ProfileError(f"{ctx}.argv must be a non-empty array of strings")
    elif not isinstance(spec["shell"], str) or not spec["shell"].strip():
        raise ProfileError(f"{ctx}.shell must be a non-empty string")
    if "timeout_seconds" not in spec:
        raise ProfileError(f"{ctx} requires timeout_seconds")
    _check_number(spec["timeout_seconds"], ctx=f"{ctx}.timeout_seconds", low=0, high=86400)
    if "cwd" in spec and (not isinstance(spec["cwd"], str) or not spec["cwd"].strip()):
        raise ProfileError(f"{ctx}.cwd must be a non-empty string")
    validate_command_env(spec.get("env"), ctx=ctx)
    return spec


def _require_command_specs(value: Any, *, field: str) -> None:
    if not isinstance(value, list):
        raise ProfileError(f"{field} must be an array")
    for i, item in enumerate(value):
        _validate_command_spec(item, ctx=f"{field}[{i}]")


# --- shared execution helpers (install.py / verify.py honor exactly these) -------------


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def resolve_guest_path(path: str | None, base: str | None) -> str:
    """Absolute guest path; relative paths resolve against ``base`` (default repo root)."""
    root = base or GUEST_REPO_ROOT
    if not root.startswith("/"):
        root = posixpath.join(GUEST_REPO_ROOT, root)
    raw = str(path or "").strip()
    if not raw:
        return posixpath.normpath(root)
    return posixpath.normpath(raw if raw.startswith("/") else posixpath.join(root, raw))


def env_exports(env: dict[str, str] | None) -> str:
    """Shell prefix applying a command env map (values single-quoted)."""
    return "".join(f"export {k}={shell_quote(str(v))}; " for k, v in (env or {}).items())


def command_spec_shell(
    spec: dict[str, Any], *, workdir: str | None, extra_env: dict[str, str] | None = None
) -> str:
    """Shell script: cd (fails hard) + env (profile defaults, then spec.env) + argv/shell."""
    cwd = resolve_guest_path(spec.get("cwd"), workdir)
    env = {**(extra_env or {}), **(spec.get("env") or {})}
    if spec.get("argv"):
        body = "exec " + " ".join(shell_quote(str(a)) for a in spec["argv"])
    elif spec.get("shell"):
        body = str(spec["shell"])
    else:
        raise ProfileError("command spec missing argv/shell")
    return f"cd {shell_quote(cwd)} || exit 1; {env_exports(env)}{body}"


def profile_probes(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Declared probes (``probes`` or the legacy ``healthcheck`` alias), as a list."""
    raw = profile.get("probes") or profile.get("healthcheck") or []
    if isinstance(raw, dict):
        raw = [raw]
    return [p for p in raw if isinstance(p, dict)]


def probe_type(probe: dict[str, Any]) -> str:
    return str(probe.get("type") or "http")


def _command_identity(spec: dict[str, Any], workdir: str | None) -> tuple[Any, ...]:
    body = ("argv", tuple(spec["argv"])) if spec.get("argv") else ("shell", spec.get("shell"))
    return (
        body,
        resolve_guest_path(spec.get("cwd"), workdir),
        tuple(sorted((spec.get("env") or {}).items())),
    )


def effective_processes(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Declared processes plus launches no declared process covers (implied ``oneshot``).

    ``run_commands`` are the app launch and, for streamable_http MCP, so is
    ``mcp.launch_command``. One that no declared process (or earlier implied launch) mirrors
    is started as an implied ``oneshot`` process (``run-<i>`` / ``mcp-launch``). For stdio MCP
    the verify helper launches ``mcp.launch_command`` itself, so that command is covered.
    """
    workdir = profile.get("workdir")
    declared = [p for p in profile.get("processes") or [] if isinstance(p, dict)]
    covered = {
        _command_identity(p["command"], workdir)
        for p in declared
        if isinstance(p.get("command"), dict)
    }
    mcp = profile.get("mcp") if isinstance(profile.get("mcp"), dict) else {}
    launch = mcp.get("launch_command") if isinstance(mcp.get("launch_command"), dict) else None
    candidates: list[tuple[str, dict[str, Any]]] = [
        (f"run-{i}", spec)
        for i, spec in enumerate(profile.get("run_commands") or [])
        if isinstance(spec, dict)
    ]
    if launch is not None:
        if mcp.get("transport") == "stdio":
            covered.add(_command_identity(launch, workdir))
        else:
            candidates.append(("mcp-launch", launch))
    out = list(declared)
    for name, spec in candidates:
        identity = _command_identity(spec, workdir)
        if identity in covered:
            continue
        covered.add(identity)
        out.append({"name": name, "command": spec, "supervise": "oneshot", "implied": True})
    return out


def service_launch_order(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable topological order over ``depends_on`` (ProfileError on unknown/cycle)."""
    by_name = {str(s.get("name")): s for s in services}
    ordered: list[dict[str, Any]] = []
    state: dict[str, int] = {}

    def visit(name: str, chain: tuple[str, ...]) -> None:
        if state.get(name) == 2:
            return
        if state.get(name) == 1:
            raise ProfileError(
                f"services: dependency cycle {' -> '.join((*chain, name))}",
                code="service_cycle",
            )
        state[name] = 1
        for dep in by_name[name].get("depends_on") or []:
            if dep not in by_name:
                raise ProfileError(f"services.{name}.depends_on: unknown service '{dep}'")
            visit(dep, (*chain, name))
        state[name] = 2
        ordered.append(by_name[name])

    for svc in services:
        visit(str(svc.get("name")), ())
    return ordered


# --- field validators ------------------------------------------------------------------


def _validate_probe(probe: Any, *, ctx: str) -> dict[str, Any]:
    if not isinstance(probe, dict):
        raise ProfileError(f"{ctx} must be an object")
    ptype = probe.get("type") or "http"
    if ptype == "mcp_handshake":
        raise _unsupported(f"{ctx}: type mcp_handshake belongs in mcp.readiness, not probes")
    if ptype not in PROBE_TYPES:
        raise _unsupported(f"{ctx}: unsupported probe type {ptype!r} (supported: http|tcp|command)")
    _reject_unknown(probe, _PROBE_COMMON_KEYS | _PROBE_TYPE_KEYS[ptype], ctx=ctx)
    if "name" in probe:
        _check_name(probe["name"], ctx=ctx)
    if "timeout_seconds" in probe:
        _check_number(probe["timeout_seconds"], ctx=f"{ctx}.timeout_seconds", low=0, high=3600)
    if "retries" in probe and (not _is_int(probe["retries"]) or not 1 <= probe["retries"] <= 120):
        raise ProfileError(f"{ctx}.retries must be an integer 1..120")
    if "interval_seconds" in probe:
        _check_number(
            probe["interval_seconds"],
            ctx=f"{ctx}.interval_seconds",
            low=0,
            high=60,
            allow_low=True,
        )
    if ptype == "http":
        url = probe.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ProfileError(f"{ctx}.url must be an http(s) URL")
        accept = probe.get("accept")
        if accept is not None and (
            not isinstance(accept, list)
            or not accept
            or not all(_is_int(c) and 100 <= c <= 599 for c in accept)
        ):
            raise ProfileError(f"{ctx}.accept must be a non-empty array of HTTP status codes")
        body = probe.get("body_contains")
        if body is not None and (not isinstance(body, str) or not body):
            raise ProfileError(f"{ctx}.body_contains must be a non-empty string")
    elif ptype == "tcp":
        if not _is_int(probe.get("port")) or not 1 <= probe["port"] <= 65535:
            raise ProfileError(f"{ctx}.port must be an integer 1..65535")
        host = probe.get("host", "127.0.0.1")
        if not isinstance(host, str) or not _HOST_RE.match(host):
            raise ProfileError(f"{ctx}.host is not a valid host")
    else:  # command
        _validate_command_spec(probe.get("command"), ctx=f"{ctx}.command")
        if "expect_exit" in probe and (
            not _is_int(probe["expect_exit"]) or not 0 <= probe["expect_exit"] <= 255
        ):
            raise ProfileError(f"{ctx}.expect_exit must be an integer 0..255")
        contains = probe.get("stdout_contains")
        if contains is not None and (not isinstance(contains, str) or not contains):
            raise ProfileError(f"{ctx}.stdout_contains must be a non-empty string")
    return probe


def _validate_probes(profile: dict[str, Any]) -> list[dict[str, Any]]:
    has_probes = "probes" in profile and profile["probes"] not in (None, [], {})
    has_health = "healthcheck" in profile and profile["healthcheck"] not in (None, [], {})
    if has_probes and has_health:
        raise ProfileError("set either probes or healthcheck, not both")
    key = "probes" if has_probes else "healthcheck"
    raw = profile.get(key)
    if raw in (None, [], {}):
        return []
    if key == "probes" and not isinstance(raw, list):
        raise ProfileError("probes must be an array")
    if key == "healthcheck" and not isinstance(raw, (dict, list)):
        raise ProfileError("healthcheck must be an object or array")
    items = [raw] if isinstance(raw, dict) else list(raw)
    names: set[str] = set()
    for i, probe in enumerate(items):
        _validate_probe(probe, ctx=f"{key}[{i}]")
        name = probe.get("name")
        if name is not None:
            if name in names:
                raise ProfileError(f"{key}[{i}]: duplicate probe name '{name}'")
            names.add(name)
    return items


def _validate_supervision(proc: dict[str, Any], *, ctx: str) -> None:
    mode = proc.get("supervise")
    if mode not in SUPERVISE_MODES:
        raise _unsupported(
            f"{ctx}.supervise must be one of {'|'.join(sorted(SUPERVISE_MODES))}, got {mode!r}"
        )
    sig = proc.get("stop_signal", "SIGTERM")
    if sig not in STOP_SIGNALS:
        raise _unsupported(f"{ctx}.stop_signal must be one of {'|'.join(sorted(STOP_SIGNALS))}")
    if "max_restarts" in proc:
        if mode != "restart":
            raise _unsupported(f"{ctx}.max_restarts only applies to supervise=restart")
        if not _is_int(proc["max_restarts"]) or not 0 <= proc["max_restarts"] <= 20:
            raise ProfileError(f"{ctx}.max_restarts must be an integer 0..20")
    if "ready_after_seconds" in proc:
        _check_number(
            proc["ready_after_seconds"],
            ctx=f"{ctx}.ready_after_seconds",
            low=0,
            high=600,
            allow_low=True,
        )


def _validate_processes(profile: dict[str, Any], probes: list[dict[str, Any]]) -> None:
    procs = profile["processes"]
    probe_names = {p["name"] for p in probes if p.get("name")}
    names: set[str] = set()
    for i, proc in enumerate(procs):
        ctx = f"processes[{i}]"
        if not isinstance(proc, dict):
            raise ProfileError(f"{ctx} must be an object")
        _reject_unknown(proc, _PROCESS_KEYS, ctx=ctx)
        name = _check_name(proc.get("name"), ctx=ctx)
        if name in names:
            raise ProfileError(f"{ctx}: duplicate process name '{name}'")
        names.add(name)
        _validate_command_spec(proc.get("command"), ctx=f"{ctx}.command")
        _validate_supervision(proc, ctx=ctx)
        ref = proc.get("ready_probe")
        if ref is not None and ref not in probe_names:
            raise ProfileError(f"{ctx}.ready_probe '{ref}' does not name a declared probe")
    proc_names = [str(p["name"]) for p in effective_processes(profile)]
    if len(set(proc_names)) != len(proc_names):
        raise ProfileError("process names (including implied run-<i>) must be unique")
    if any(n.startswith("svc-") for n in proc_names):
        raise ProfileError("process names must not start with the reserved prefix 'svc-'")


def _validate_services(profile: dict[str, Any]) -> None:
    services = profile["services"]
    names: set[str] = set()
    ports_seen: dict[int, str] = {}
    for i, svc in enumerate(services):
        ctx = f"services[{i}]"
        if not isinstance(svc, dict):
            raise ProfileError(f"{ctx} must be an object")
        if "image" in svc:
            raise _unsupported(
                f"{ctx}: image-based services are not supported; "
                "use package + command to install and start the service in the guest"
            )
        _reject_unknown(svc, _SERVICE_KEYS, ctx=ctx)
        name = _check_name(svc.get("name"), ctx=ctx)
        if name in names:
            raise ProfileError(f"{ctx}: duplicate service name '{name}'")
        names.add(name)
        kind = svc.get("kind")
        if not isinstance(kind, str) or not kind.strip():
            raise ProfileError(f"{ctx}.kind is required")
        pkg = svc.get("package")
        if pkg is not None:
            pkgs = [pkg] if isinstance(pkg, str) else pkg
            if not isinstance(pkgs, list) or not all(
                isinstance(p, str) and _PACKAGE_RE.match(p) for p in pkgs
            ):
                raise ProfileError(f"{ctx}.package must be a package name or array of names")
        _validate_command_spec(svc.get("command"), ctx=f"{ctx}.command")
        ports = svc.get("ports")
        if (
            not isinstance(ports, list)
            or not ports
            or not all(_is_int(p) and 1 <= p <= 65535 for p in ports)
        ):
            raise ProfileError(f"{ctx}.ports must be a non-empty array of ports")
        for port in ports:
            if port in ports_seen:
                raise ProfileError(f"{ctx}: port {port} already claimed by '{ports_seen[port]}'")
            ports_seen[port] = name
        validate_command_env(svc.get("env"), ctx=ctx)
        if "healthcheck" not in svc:
            raise ProfileError(f"{ctx}.healthcheck is required")
        if isinstance(svc["healthcheck"], list):
            raise ProfileError(f"{ctx}.healthcheck must be a single probe object")
        _validate_probe(svc["healthcheck"], ctx=f"{ctx}.healthcheck")
        deps = svc.get("depends_on", [])
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            raise ProfileError(f"{ctx}.depends_on must be an array of service names")
        if name in deps:
            raise ProfileError(f"{ctx}.depends_on cannot include itself")
        if "optional" in svc and not isinstance(svc["optional"], bool):
            raise ProfileError(f"{ctx}.optional must be a boolean")
        svc_proc = {"supervise": "restart", **{k: v for k, v in svc.items() if k in _SUPERVISION}}
        _validate_supervision(svc_proc, ctx=ctx)
    service_launch_order(services)
    for svc in services:
        if svc.get("optional"):
            continue
        for dep in svc.get("depends_on") or []:
            target = next(s for s in services if s["name"] == dep)
            if target.get("optional"):
                raise ProfileError(
                    f"services.{svc['name']} is required but depends on optional '{dep}'"
                )


def _validate_mcp(profile: dict[str, Any]) -> None:
    mcp = _require(profile, "mcp", ctx="git_mcp")
    if not isinstance(mcp, dict):
        raise ProfileError("mcp must be an object")
    _reject_unknown(mcp, _MCP_KEYS, ctx="mcp")
    transport = mcp.get("transport")
    if transport not in {"stdio", "streamable_http"}:
        raise ProfileError("mcp.transport must be stdio|streamable_http")
    launch = mcp.get("launch_command")
    if not isinstance(launch, dict):
        raise ProfileError("mcp.launch_command is required")
    _validate_command_spec(launch, ctx="mcp.launch_command")
    if "cwd" in mcp and (not isinstance(mcp["cwd"], str) or not mcp["cwd"].strip()):
        raise ProfileError("mcp.cwd must be a non-empty string")
    readiness = mcp.get("readiness")
    if not isinstance(readiness, dict) or readiness.get("type") != "mcp_handshake":
        raise ProfileError("mcp.readiness.type must be mcp_handshake")
    _reject_unknown(readiness, _MCP_READINESS_KEYS, ctx="mcp.readiness")
    if readiness.get("transport", transport) != transport:
        raise ProfileError("mcp.readiness.transport must equal mcp.transport")
    if "timeout_seconds" in readiness:
        _check_number(
            readiness["timeout_seconds"], ctx="mcp.readiness.timeout_seconds", low=0, high=3600
        )
    if transport == "streamable_http":
        url = mcp.get("url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ProfileError("mcp.url required for streamable_http")
    else:
        if mcp.get("url"):
            raise _unsupported("mcp.url applies only to streamable_http")
        if profile.get("processes"):
            raise _unsupported(
                "stdio MCP: processes[] is not supported (the verify helper owns the "
                "server subprocess); use mcp.launch_command"
            )
        if profile.get("ports"):
            raise _unsupported("stdio MCP: ports[] is not supported")
        if profile.get("probes") or profile.get("healthcheck"):
            raise _unsupported("stdio MCP: probes are not supported; readiness is mcp.readiness")
        if effective_processes(profile):
            raise _unsupported(
                "stdio MCP: run_commands must equal mcp.launch_command "
                "(the handshake helper is the only launcher)"
            )


def validate_profile(
    profile: dict[str, Any],
    *,
    phase: ProfilePhase,
) -> dict[str, Any]:
    """Validate bootstrap or runtime profile; return the same dict if ok."""
    if not isinstance(profile, dict):
        raise ProfileError("profile must be an object")
    if profile.get("schema_version") != SCHEMA_VERSION:
        raise ProfileError(
            f"schema_version must be '{SCHEMA_VERSION}'",
            code="schema_version",
        )
    intent = profile.get("intent")
    if phase == "bootstrap":
        if intent != "bootstrap":
            raise ProfileError("bootstrap phase requires intent=bootstrap")
        _require(profile, "oci_image", ctx="bootstrap")
        _require(profile, "workdir", ctx="bootstrap")
        if profile.get("install_commands") not in ([], None):
            # Allow missing; if present must be empty for bootstrap.
            if profile.get("install_commands"):
                raise ProfileError("bootstrap profile must not install packages")
        if profile.get("run_commands") not in ([], None):
            if profile.get("run_commands"):
                raise ProfileError("bootstrap profile must not run the app")
        for key in ("services", "processes", "packages"):
            if profile.get(key):
                raise _unsupported(f"bootstrap profile must not declare {key}")
        return profile

    if intent not in RUNTIME_INTENTS:
        raise ProfileError(
            "runtime intent must be git_mcp|webapp|demo",
            code="intent",
        )
    for key in (
        "source",
        "runtime",
        "os_image",
        "workdir",
        "services",
        "packages",
        "install_commands",
        "run_commands",
        "processes",
        "ports",
        "summary",
        "verification_target",
    ):
        _require(profile, key, ctx="runtime")

    source = profile["source"]
    if not isinstance(source, dict):
        raise ProfileError("source must be an object")
    if source.get("type") != "git":
        raise ProfileError("source.type must be git")
    if not source.get("url"):
        raise ProfileError("source.url is required")
    commit = source.get("commit")
    if not isinstance(commit, str) or not _SHA_RE.match(commit):
        raise ProfileError(
            "source.commit must be a full 40-char SHA (D62)",
            code="missing_commit",
        )

    vt = profile.get("verification_target")
    if vt not in {"original_application", "generated_demo"}:
        raise ProfileError("verification_target invalid")

    _reject_unknown(profile, TOP_LEVEL_KEYS, ctx="profile")
    _require_command_specs(profile["install_commands"], field="install_commands")
    _require_command_specs(profile["run_commands"], field="run_commands")

    for key in ("services", "packages", "processes", "ports"):
        if not isinstance(profile[key], list):
            raise ProfileError(f"{key} must be an array")
    for i, pkg in enumerate(profile["packages"]):
        if not isinstance(pkg, str) or not _PACKAGE_RE.match(pkg):
            raise ProfileError(f"packages[{i}] must be a package name string")
    for i, port in enumerate(profile["ports"]):
        if not _is_int(port) or not 1 <= port <= 65535:
            raise ProfileError(f"ports[{i}] must be an integer 1..65535")
    if not isinstance(profile["workdir"], str) or not profile["workdir"].strip():
        raise ProfileError("workdir must be a non-empty string")

    probes = _validate_probes(profile)
    _validate_processes(profile, probes)
    _validate_services(profile)

    if intent == "git_mcp":
        _validate_mcp(profile)
    elif "mcp" in profile:
        raise _unsupported(f"mcp is only supported for git_mcp, not {intent}")

    if intent in {"webapp", "demo"} and not probes:
        raise ProfileError(f"{intent} profile requires probes or healthcheck")

    return profile


def persist_profile_revision(
    job_id: str,
    profile: dict[str, Any],
    *,
    phase: ProfilePhase,
    settings: Settings | None = None,
) -> Any:
    """Validate, write storage/profiles/{job_id}/, append ledger revision (D64)."""
    cfg = settings or get_settings()
    validate_profile(profile, phase=phase)
    ledger = get_ledger(cfg)
    root = profiles_root(cfg) / job_id
    root.mkdir(parents=True, exist_ok=True)
    existing = ledger.list_profile_revisions(job_id)
    next_rev = (existing[-1].revision + 1) if existing else 1
    abs_path = root / f"r{next_rev}.json"
    storage_path = str(abs_path)
    abs_path.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "environment_profile.json").write_text(
        abs_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return ledger.append_profile_revision(
        job_id,
        phase=phase,
        schema_version=str(profile["schema_version"]),
        profile=profile,
        storage_path=storage_path,
    )


def assert_runtime_ready_for_provision(profile: dict[str, Any]) -> None:
    """Invalid runtime profiles must not start provision/install (D36)."""
    try:
        validate_profile(profile, phase="runtime")
    except ProfileError as exc:
        raise HarnessError(
            f"runtime profile blocks provision: {exc.message}",
            code="profile_blocks_provision",
        ) from exc
