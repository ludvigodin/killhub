"""LLM-assisted discovery and repair of the runtime profile (D85, D8, D47, D29).

Plane 1 only. The model is a *planner*: it reads sandbox-collected evidence and
proposes an ``environment_profile``. Everything it returns is treated as
untrusted until :func:`sanitize_profile` has rebuilt it from an allowlist of
fields, pinned the trusted facts (source URL, resolved commit, OCI image),
applied the phase locks, and ``validate_profile`` has accepted it. Only then do
callers persist a revision and execute it - inside Plane 2 via the harness.

Inference goes through ``EnvironmentAgent`` (Vultr Serverless Inference only,
D25) with ``job_id`` so token budgets are recorded and enforced. Any failure
here (no key, over budget, bad JSON, rejected profile, deadline) returns
``None`` and the caller keeps its heuristic / unchanged plan. The model never
decides readiness or success (D47).
"""

from __future__ import annotations

import copy
import json
import logging
import posixpath
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from profile import (
    GUEST_REPO_ROOT,
    RUNTIME_INTENTS,
    ProfileError,
    validate_profile,
)
from typing import Any
from urllib.parse import urlparse

from agent import AgentError, EnvironmentAgent
from config import Settings
from jobs import get_ledger

logger = logging.getLogger("killhub.plan_llm")

# Bounds on what a model may ask the sandbox to do (cheap sanity, not an allowlist: D29).
MAX_INSPECT_CHARS = 24_000
MAX_EVIDENCE_CHARS = 6_000
MAX_INSTALL_COMMANDS = 12
MAX_RUN_COMMANDS = 4
MAX_PROCESSES = 4
MAX_PACKAGES = 30
MAX_PORTS = 8
MAX_PROBES = 4
MAX_SERVICES = 4
MAX_TIMEOUT_SECONDS = 3600

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_FORBIDDEN_FRAGMENTS = (
    "vultr_",
    "opencode_",
    "169.254.169.254",
    "metadata.google",
    "killhub.pro",
)

# Fields a verify-phase (offline) repair may not change: nothing can be installed
# any more and the verification label must not flip mid-flight.
VERIFY_LOCKED_FIELDS = ("packages", "install_commands", "intent", "verification_target", "runtime")


class PlanLLMError(Exception):
    def __init__(self, message: str, *, code: str = "plan_rejected") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class TrustedFacts:
    """Values the model is never allowed to choose."""

    git_url: str
    commit: str
    ref: str
    oci_image: str


@dataclass
class PlanProposal:
    profile: dict[str, Any]
    rationale: str
    changes: list[str] = field(default_factory=list)
    changed: bool = True
    model: str = ""
    tokens: int = 0


# ---------------------------------------------------------------------------
# Deadlines / events
# ---------------------------------------------------------------------------


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def deadline_exceeded(expires_at: str | None, *, now: datetime | None = None) -> bool:
    """True when the job's absolute ``expires_at`` has passed (D41, D83)."""
    expires = _parse_iso(expires_at)
    if expires is None:
        return False
    return expires <= (now or datetime.now(timezone.utc))


def _event(
    job_id: str,
    name: str,
    *,
    settings: Settings,
    status: str,
    **detail: Any,
) -> None:
    ledger = get_ledger(settings)
    ledger.append_event(
        job_id,
        typ="span",
        message=name,
        payload={"span": name, "status": status, **detail},
    )
    ledger.append_event(
        job_id,
        typ="log",
        message=f"{name} {status}",
        payload={"kind": "plan_llm", "span": name, "status": status, **detail},
    )


# ---------------------------------------------------------------------------
# Sanitizer (model output is untrusted)
# ---------------------------------------------------------------------------


def _forbidden_fragments(settings: Settings) -> tuple[str, ...]:
    hosts = [
        h.strip().lower() for h in (settings.control_plane_deny_hosts or "").split(",") if h.strip()
    ]
    return (*_FORBIDDEN_FRAGMENTS, *hosts)


def _reject_forbidden(text: str, *, ctx: str, forbidden: tuple[str, ...]) -> None:
    low = text.lower()
    for frag in forbidden:
        if frag and frag in low:
            raise PlanLLMError(f"{ctx} references forbidden target {frag!r}", code="plan_forbidden")


def _guest_path(value: Any, *, ctx: str, base: str = GUEST_REPO_ROOT) -> str:
    """Absolute guest path under the checkout root; relative values resolve against ``base``."""
    if not isinstance(value, str) or not value.strip():
        raise PlanLLMError(f"{ctx} must be a path string")
    raw = value.strip()
    path = posixpath.normpath(raw if raw.startswith("/") else posixpath.join(base, raw))
    if path != GUEST_REPO_ROOT and not path.startswith(GUEST_REPO_ROOT + "/"):
        raise PlanLLMError(f"{ctx} must be under {GUEST_REPO_ROOT}", code="plan_forbidden")
    return path


def _int_in(value: Any, *, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


_ENV_DENY_PREFIXES = ("VULTR_", "OPENCODE_", "KILLHUB_", "MSB_", "KH_", "LD_", "DYLD_")
_ENV_DENY_NAMES = frozenset({"BASH_ENV", "ENV", "IFS", "SHELLOPTS", "PS4"})


def _clean_env(env: Any, *, ctx: str) -> dict[str, str]:
    """Plain config env only (PORT, NODE_ENV, ...): never Killhub secrets or loader hijacks."""
    if not env:
        return {}
    if not isinstance(env, dict) or len(env) > 16:
        raise PlanLLMError(f"{ctx}.env must be an object of at most 16 entries")
    out: dict[str, str] = {}
    for key, value in env.items():
        name = str(key)
        valid = bool(name) and (name[0].isalpha() or name[0] == "_")
        valid = valid and all(c.isalnum() or c == "_" for c in name)
        if not valid:
            raise PlanLLMError(f"{ctx}.env has invalid name {name!r}")
        upper = name.upper()
        if upper.startswith(_ENV_DENY_PREFIXES) or upper in _ENV_DENY_NAMES:
            raise PlanLLMError(f"{ctx}.env.{name} is not permitted", code="plan_forbidden")
        text = str(value)
        if len(text) > 500 or "\x00" in text:
            raise PlanLLMError(f"{ctx}.env.{name} value invalid")
        out[name] = text
    return out


def _clean_command(
    spec: Any,
    *,
    ctx: str,
    workdir: str,
    forbidden: tuple[str, ...],
    uv_installer: str,
) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise PlanLLMError(f"{ctx} must be an object")
    out: dict[str, Any] = {}
    argv = spec.get("argv")
    shell = spec.get("shell")
    if isinstance(argv, list) and argv:
        if len(argv) > 64:
            raise PlanLLMError(f"{ctx}.argv too long")
        items = [str(a) for a in argv]
        if any(len(a) > 1000 for a in items):
            raise PlanLLMError(f"{ctx}.argv entry too long")
        out["argv"] = items
        scan = " ".join(items)
    elif isinstance(shell, str) and shell.strip():
        if len(shell) > 4000:
            raise PlanLLMError(f"{ctx}.shell too long")
        out["shell"] = shell
        scan = shell
        if shell == uv_installer:
            # Exact Killhub tooling snippet: keep attribution out of the repo's own steps.
            out["killhub_tooling"] = True
    else:
        raise PlanLLMError(f"{ctx} requires argv or shell")
    _reject_forbidden(scan, ctx=ctx, forbidden=forbidden)
    out["cwd"] = (
        _guest_path(spec["cwd"], ctx=f"{ctx}.cwd", base=workdir) if spec.get("cwd") else workdir
    )
    env = _clean_env(spec.get("env"), ctx=ctx)
    if env:
        out["env"] = env
    out["timeout_seconds"] = _int_in(
        spec.get("timeout_seconds"), lo=1, hi=MAX_TIMEOUT_SECONDS, default=120
    )
    return out


_IGNORE_SCRIPTS_RE = re.compile(r"\s--ignore-scripts(?:=true)?(?=\s|$|;|&|\|)")
_IGNORE_SCRIPTS_ENV = {"NPM_CONFIG_IGNORE_SCRIPTS", "npm_config_ignore_scripts"}


def _run_install_scripts(commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Install steps must run the repo's lifecycle scripts.

    Running a repo's install scripts inside the disposable, network-phased
    sandbox is how Killhub observes install-time behaviour (active checks:
    canary exfiltration, persistence writes). A planner that adds
    ``--ignore-scripts`` would hide a malicious ``postinstall`` and report the
    repo as clean, so the flag (and its env-var form) is removed here.
    """
    out: list[dict[str, Any]] = []
    for cmd in commands:
        cmd = dict(cmd)
        if "argv" in cmd:
            cmd["argv"] = [
                a for a in cmd["argv"] if a not in {"--ignore-scripts", "--ignore-scripts=true"}
            ]
        if "shell" in cmd and not cmd.get("killhub_tooling"):
            cmd["shell"] = _IGNORE_SCRIPTS_RE.sub("", cmd["shell"])
        if "env" in cmd:
            env = {k: v for k, v in cmd["env"].items() if k not in _IGNORE_SCRIPTS_ENV}
            if env:
                cmd["env"] = env
            else:
                cmd.pop("env")
        out.append(cmd)
    return out


def _clean_commands(
    items: Any,
    *,
    ctx: str,
    limit: int,
    workdir: str,
    forbidden: tuple[str, ...],
    uv_installer: str,
) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise PlanLLMError(f"{ctx} must be an array")
    if len(items) > limit:
        raise PlanLLMError(f"{ctx} has more than {limit} entries")
    return [
        _clean_command(
            item,
            ctx=f"{ctx}[{i}]",
            workdir=workdir,
            forbidden=forbidden,
            uv_installer=uv_installer,
        )
        for i, item in enumerate(items)
    ]


def _loopback_url(url: Any, *, ctx: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise PlanLLMError(f"{ctx} requires a url")
    parsed = urlparse(url.strip())
    if parsed.scheme != "http" or (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        raise PlanLLMError(f"{ctx} must be http on loopback", code="plan_forbidden")
    return url.strip()


def _clean_probes(items: Any, *, ctx: str) -> list[dict[str, Any]]:
    if items is None:
        return []
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or len(items) > MAX_PROBES:
        raise PlanLLMError(f"{ctx} must be an array of at most {MAX_PROBES}")
    out: list[dict[str, Any]] = []
    for i, probe in enumerate(items):
        if not isinstance(probe, dict):
            raise PlanLLMError(f"{ctx}[{i}] must be an object")
        ptype = probe.get("type") or "http"
        if ptype != "http":
            # Prefer http probes in LLM proposals; profile validation owns the full set.
            raise PlanLLMError(
                f"{ctx}[{i}].type {ptype!r} is not supported", code="plan_unsupported"
            )
        accept = probe.get("accept") or [200]
        if not isinstance(accept, list):
            accept = [accept]
        codes = sorted({_int_in(c, lo=100, hi=599, default=200) for c in accept}) or [200]
        out.append(
            {
                "name": str(probe.get("name") or f"http-{i}")[:40],
                "type": "http",
                "url": _loopback_url(probe.get("url"), ctx=f"{ctx}[{i}]"),
                "accept": codes,
                "timeout_seconds": _int_in(probe.get("timeout_seconds"), lo=1, hi=120, default=10),
            }
        )
    return out


def _clean_processes(
    items: Any,
    *,
    workdir: str,
    forbidden: tuple[str, ...],
    uv_installer: str,
) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MAX_PROCESSES:
        raise PlanLLMError(f"processes must be an array of at most {MAX_PROCESSES}")
    out: list[dict[str, Any]] = []
    for i, proc in enumerate(items):
        if not isinstance(proc, dict):
            raise PlanLLMError(f"processes[{i}] must be an object")
        name = str(proc.get("name") or f"proc{i}").strip().lower()
        if not _name_ok(name):
            raise PlanLLMError(f"processes[{i}].name invalid")
        supervise = str(proc.get("supervise") or "restart")
        if supervise == "none":
            supervise = "oneshot"
        if supervise not in {"restart", "oneshot"}:
            raise PlanLLMError(f"processes[{i}].supervise must be restart|oneshot")
        entry: dict[str, Any] = {
            "name": name,
            "command": _clean_command(
                proc.get("command"),
                ctx=f"processes[{i}].command",
                workdir=workdir,
                forbidden=forbidden,
                uv_installer=uv_installer,
            ),
            "supervise": supervise,
            "ready_after_seconds": _int_in(proc.get("ready_after_seconds"), lo=0, hi=60, default=1),
        }
        if proc.get("ready_probe"):
            entry["ready_probe"] = str(proc["ready_probe"])[:40]
        out.append(entry)
    return out


def _name_ok(name: str) -> bool:
    return bool(name) and len(name) <= 32 and all(c.isalnum() or c in "_-" for c in name)


def _clean_packages(items: Any) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MAX_PACKAGES:
        raise PlanLLMError(f"packages must be an array of at most {MAX_PACKAGES}")
    out: list[str] = []
    for pkg in items:
        name = str(pkg).strip()
        ok = (
            name
            and len(name) <= 64
            and name[0].isalnum()
            and all(c.isalnum() or c in "+._:=~-" for c in name)
        )
        if not ok:
            raise PlanLLMError(f"invalid package name {name!r}")
        if name not in out:
            out.append(name)
    return out


def _clean_services(
    items: Any,
    *,
    workdir: str,
    forbidden: tuple[str, ...],
    uv_installer: str,
) -> list[dict[str, Any]]:
    """Backing services (db/cache). Provisioning is executed by install/verify (P2)."""
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MAX_SERVICES:
        raise PlanLLMError(f"services must be an array of at most {MAX_SERVICES}")
    out: list[dict[str, Any]] = []
    for i, svc in enumerate(items):
        if isinstance(svc, str):
            svc = {"name": svc}
        if not isinstance(svc, dict) or not svc.get("name"):
            raise PlanLLMError(f"services[{i}] needs a name")
        entry: dict[str, Any] = {"name": str(svc["name"])[:40]}
        if svc.get("kind"):
            entry["kind"] = str(svc["kind"])[:40]
        if svc.get("package"):
            pkgs = svc["package"] if isinstance(svc["package"], list) else [svc["package"]]
            cleaned = _clean_packages(pkgs)
            entry["package"] = cleaned[0] if isinstance(svc["package"], str) else cleaned
        if svc.get("command"):
            entry["command"] = _clean_command(
                svc["command"],
                ctx=f"services[{i}].command",
                workdir=workdir,
                forbidden=forbidden,
                uv_installer=uv_installer,
            )
        if svc.get("ports"):
            entry["ports"] = _clean_ports(svc["ports"])
        if isinstance(svc.get("depends_on"), list):
            entry["depends_on"] = [str(d)[:40] for d in svc["depends_on"]][:MAX_SERVICES]
        if isinstance(svc.get("optional"), bool):
            entry["optional"] = svc["optional"]
        out.append(entry)
    return out


def _clean_mcp(
    mcp: Any,
    *,
    workdir: str,
    forbidden: tuple[str, ...],
    uv_installer: str,
) -> dict[str, Any]:
    if not isinstance(mcp, dict):
        raise PlanLLMError("git_mcp requires an mcp object")
    transport = mcp.get("transport")
    if transport not in {"stdio", "streamable_http"}:
        raise PlanLLMError("mcp.transport must be stdio|streamable_http")
    launch = _clean_command(
        mcp.get("launch_command"),
        ctx="mcp.launch_command",
        workdir=workdir,
        forbidden=forbidden,
        uv_installer=uv_installer,
    )
    readiness = mcp.get("readiness") if isinstance(mcp.get("readiness"), dict) else {}
    out: dict[str, Any] = {
        "transport": transport,
        "entrypoint": str(mcp.get("entrypoint") or "")[:200],
        "launch_command": launch,
        "cwd": (
            _guest_path(mcp["cwd"], ctx="mcp.cwd", base=workdir)
            if mcp.get("cwd")
            else launch["cwd"]
        ),
        "readiness": {
            "type": "mcp_handshake",
            "transport": transport,
            "timeout_seconds": _int_in(readiness.get("timeout_seconds"), lo=5, hi=300, default=60),
        },
    }
    if transport == "streamable_http":
        out["url"] = _loopback_url(mcp.get("url"), ctx="mcp.url")
    # mcp.security_assessment (D35) is operator/fixture-owned; never model-authored.
    return out


def _original_failure_for_demo(
    original_failure: dict[str, Any] | None, *, fallback_summary: str, step: str
) -> dict[str, Any]:
    if original_failure:
        return dict(original_failure)
    return {"step": step, "summary": fallback_summary}


def sanitize_profile(
    raw: Any,
    *,
    facts: TrustedFacts,
    settings: Settings,
    current: dict[str, Any] | None = None,
    locked: tuple[str, ...] = (),
    original_failure: dict[str, Any] | None = None,
    demo_reason: str = "",
    step: str = "discover",
) -> dict[str, Any]:
    """Rebuild a runtime profile from an allowlist; raise PlanLLMError if unusable.

    Trusted facts always win. ``locked`` fields are copied verbatim from
    ``current`` (verify phase). The result has passed ``validate_profile`` and
    the D62 built-checkout launch rule.
    """
    # Lazy: discover and verify import this module at top level.
    from discover import UV_INSTALLER
    from verify import VerifyError, assert_built_checkout_launch

    if not isinstance(raw, dict):
        raise PlanLLMError("profile must be an object")
    if current is not None and "intent" in locked:
        raw = {**raw, "intent": current.get("intent")}
    forbidden = _forbidden_fragments(settings)
    workdir = _guest_path(raw.get("workdir") or GUEST_REPO_ROOT, ctx="workdir")

    intent = raw.get("intent")
    if intent not in RUNTIME_INTENTS:
        raise PlanLLMError("intent must be git_mcp|webapp|demo", code="plan_intent")

    profile: dict[str, Any] = {
        "schema_version": "1",
        "intent": intent,
        "source": {
            "type": "git",
            "url": facts.git_url,
            "commit": facts.commit,
            "ref": facts.ref,
        },
        "runtime": str(raw.get("runtime") or "unknown")[:40],
        "os_image": "linux",
        "oci_image": facts.oci_image,
        "workdir": workdir,
        "services": _clean_services(
            raw.get("services"),
            workdir=workdir,
            forbidden=forbidden,
            uv_installer=UV_INSTALLER,
        ),
        "packages": _clean_packages(raw.get("packages")),
        "install_commands": _run_install_scripts(
            _clean_commands(
                raw.get("install_commands"),
                ctx="install_commands",
                limit=MAX_INSTALL_COMMANDS,
                workdir=workdir,
                forbidden=forbidden,
                uv_installer=UV_INSTALLER,
            )
        ),
        "run_commands": _clean_commands(
            raw.get("run_commands"),
            ctx="run_commands",
            limit=MAX_RUN_COMMANDS,
            workdir=workdir,
            forbidden=forbidden,
            uv_installer=UV_INSTALLER,
        ),
        "processes": _clean_processes(
            raw.get("processes"),
            workdir=workdir,
            forbidden=forbidden,
            uv_installer=UV_INSTALLER,
        ),
        "ports": _clean_ports(raw.get("ports")),
        "summary": str(raw.get("summary") or "LLM-planned environment")[:300],
    }
    probes = _clean_probes(raw.get("probes") or raw.get("healthcheck"), ctx="probes")
    if probes:
        profile["probes"] = probes
    if intent == "git_mcp":
        profile["mcp"] = _clean_mcp(
            raw.get("mcp"), workdir=workdir, forbidden=forbidden, uv_installer=UV_INSTALLER
        )

    if intent == "demo":
        profile["verification_target"] = "generated_demo"
        profile["original_failure"] = _original_failure_for_demo(
            original_failure,
            fallback_summary=(
                "no git_mcp/webapp fit; planner generated a demo"
                + (f": {demo_reason}" if demo_reason else "")
            ),
            step=step,
        )
    else:
        profile["verification_target"] = "original_application"

    if current is not None:
        for key in locked:
            if key in current:
                profile[key] = copy.deepcopy(current[key])
        if "original_failure" in current and profile.get("verification_target") == "generated_demo":
            profile.setdefault("original_failure", copy.deepcopy(current["original_failure"]))
    try:
        validate_profile(profile, phase="runtime")
        assert_built_checkout_launch(profile, resolved_commit=facts.commit)
    except ProfileError as exc:
        raise PlanLLMError(exc.message, code=f"plan_{exc.code}") from exc
    except VerifyError as exc:
        raise PlanLLMError(exc.message, code=f"plan_{exc.code}") from exc
    return profile


def _clean_ports(items: Any) -> list[int]:
    if items is None:
        return []
    if not isinstance(items, list) or len(items) > MAX_PORTS:
        raise PlanLLMError(f"ports must be an array of at most {MAX_PORTS}")
    out: list[int] = []
    for p in items:
        try:
            n = int(p)
        except (TypeError, ValueError) as exc:
            raise PlanLLMError(f"invalid port {p!r}") from exc
        if not 1 <= n <= 65535:
            raise PlanLLMError(f"invalid port {n}")
        if n not in out:
            out.append(n)
    return out


def diff_profiles(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Top-level keys whose value changed (summary excluded)."""
    skip = {"summary"}
    keys = (set(old) | set(new)) - skip
    return sorted(k for k in keys if old.get(k) != new.get(k))


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Trusted, host-owned prompt text (never from a submitted checkout)."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _system_prompt(*names: str) -> str:
    return "\n\n---\n\n".join(load_prompt(n).strip() for n in names)


def _untrusted(label: str, text: str, limit: int) -> str:
    body = (text or "")[:limit]
    return f"<<<UNTRUSTED {label} BEGIN>>>\n{body}\n<<<UNTRUSTED {label} END>>>"


def _facts_dict(facts: TrustedFacts) -> dict[str, str]:
    return {
        "git_url": facts.git_url,
        "resolved_commit": facts.commit,
        "oci_image": facts.oci_image,
        "workdir": GUEST_REPO_ROOT,
    }


def build_discovery_user_message(
    *,
    facts: TrustedFacts,
    inspect: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> str:
    from discover import UV_INSTALLER

    header = {
        "task": "discover",
        "facts": _facts_dict(facts),
        "uv_installer": UV_INSTALLER,
        "heuristic_baseline": baseline,
        "signals": {
            k: inspect.get(k)
            for k in ("has_package_json", "has_filesystem_mcp", "mentions_express", "python_mcp")
        },
    }
    return (
        json.dumps(header, indent=2, sort_keys=True, default=str)
        + "\n\n"
        + _untrusted("CHECKOUT INSPECTION", str(inspect.get("raw") or ""), MAX_INSPECT_CHARS)
    )


def build_repair_user_message(
    *,
    facts: TrustedFacts,
    profile: dict[str, Any],
    phase: str,
    attempt: int,
    max_attempts: int,
    failures: list[dict[str, Any]],
    evidence: str,
    locked: tuple[str, ...],
) -> str:
    header = {
        "task": "repair",
        "phase": phase,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "facts": _facts_dict(facts),
        "locked_fields": list(locked),
        "failures": failures,
        "current_profile": profile,
    }
    return (
        json.dumps(header, indent=2, sort_keys=True, default=str)
        + "\n\n"
        + _untrusted("SANDBOX EVIDENCE", evidence, MAX_EVIDENCE_CHARS)
    )


# ---------------------------------------------------------------------------
# Public entry points (called via EnvironmentAgent methods)
# ---------------------------------------------------------------------------


def _unwrap(reply: dict[str, Any]) -> tuple[Any, str, list[str]]:
    profile = reply.get("profile") if isinstance(reply.get("profile"), dict) else None
    if profile is None and reply.get("intent"):
        profile = reply  # tolerate a bare profile
    rationale = str(reply.get("rationale") or "").strip()[:800]
    changes = [str(c)[:300] for c in (reply.get("changes") or reply.get("evidence") or [])][:12]
    return profile, rationale, changes


def propose_discovery_profile(
    agent: EnvironmentAgent,
    *,
    facts: TrustedFacts,
    inspect: dict[str, Any],
    baseline: dict[str, Any] | None,
    expires_at: str | None = None,
) -> PlanProposal | None:
    """Ask the model for a runtime profile from inspect evidence. None = use heuristics."""
    cfg = agent.settings
    job_id = agent.job_id
    name = "plan_llm_discover"
    if deadline_exceeded(expires_at):
        _event(job_id, name, settings=cfg, status="skipped", reason="deadline_exceeded")
        return None
    ok, reason = agent.inference_available()
    if not ok:
        _event(job_id, name, settings=cfg, status="skipped", reason=reason)
        return None
    try:
        reply, result = agent.infer_json(
            system=_system_prompt("discover_environment", "validate_environment_spec"),
            user=build_discovery_user_message(facts=facts, inspect=inspect, baseline=baseline),
        )
        raw_profile, rationale, changes = _unwrap(reply)
        profile = sanitize_profile(
            raw_profile,
            facts=facts,
            settings=cfg,
            demo_reason=rationale,
            step="discover",
        )
    except AgentError as exc:
        _event(job_id, name, settings=cfg, status="skipped", reason=exc.code)
        return None
    except PlanLLMError as exc:
        _event(job_id, name, settings=cfg, status="rejected", reason=exc.code, error=exc.message)
        return None
    _event(
        job_id,
        name,
        settings=cfg,
        status="ok",
        intent=profile["intent"],
        model=result.model,
        tokens=result.total_tokens,
        rationale=rationale,
    )
    return PlanProposal(
        profile=profile,
        rationale=rationale,
        changes=changes,
        model=result.model,
        tokens=result.total_tokens,
    )


def propose_repair_profile(
    agent: EnvironmentAgent,
    *,
    facts: TrustedFacts,
    profile: dict[str, Any],
    phase: str,
    attempt: int,
    max_attempts: int,
    failures: list[dict[str, Any]],
    evidence: str,
    expires_at: str | None = None,
) -> PlanProposal | None:
    """Ask the model to revise ``profile`` after a real failure. None = retry as-is."""
    cfg = agent.settings
    job_id = agent.job_id
    name = f"plan_llm_repair_{phase}"
    if phase not in {"install", "verify"}:
        raise ValueError(f"unknown repair phase {phase!r}")
    if deadline_exceeded(expires_at):
        _event(job_id, name, settings=cfg, status="skipped", reason="deadline_exceeded")
        return None
    ok, reason = agent.inference_available()
    if not ok:
        _event(job_id, name, settings=cfg, status="skipped", reason=reason, attempt=attempt)
        return None
    locked = VERIFY_LOCKED_FIELDS if phase == "verify" else ()
    first_failure = failures[0] if failures else {}
    original_failure = {
        "step": phase,
        "summary": (
            f"{phase} failed: {first_failure.get('name', 'unknown')} "
            f"(exit {first_failure.get('exit_code')})"
        )[:300],
    }
    try:
        reply, result = agent.infer_json(
            system=_system_prompt("repair_environment", "validate_environment_spec"),
            user=build_repair_user_message(
                facts=facts,
                profile=profile,
                phase=phase,
                attempt=attempt,
                max_attempts=max_attempts,
                failures=failures,
                evidence=evidence,
                locked=locked,
            ),
        )
        raw_profile, rationale, changes = _unwrap(reply)
        if not rationale:
            raise PlanLLMError("repair revision requires a rationale", code="plan_unjustified")
        revised = sanitize_profile(
            raw_profile,
            facts=facts,
            settings=cfg,
            current=profile,
            locked=locked,
            original_failure=original_failure,
            step=phase,
        )
    except AgentError as exc:
        _event(job_id, name, settings=cfg, status="skipped", reason=exc.code, attempt=attempt)
        return None
    except PlanLLMError as exc:
        _event(
            job_id,
            name,
            settings=cfg,
            status="rejected",
            reason=exc.code,
            error=exc.message,
            attempt=attempt,
        )
        return None
    changed_keys = diff_profiles(profile, revised)
    _event(
        job_id,
        name,
        settings=cfg,
        status="ok" if changed_keys else "unchanged",
        attempt=attempt,
        changed=changed_keys,
        rationale=rationale,
        model=result.model,
        tokens=result.total_tokens,
    )
    return PlanProposal(
        profile=revised,
        rationale=rationale,
        changes=changes or [f"changed: {', '.join(changed_keys)}"],
        changed=bool(changed_keys),
        model=result.model,
        tokens=result.total_tokens,
    )
