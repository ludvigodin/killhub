"""Bootstrap sandbox → inspect → validated runtime profile (D36, D62, D34).

Clone/inspect runs inside Plane 2 via harness exec — never privileged host install
of untrusted repos. Image replace (oci_image ≠ bootstrap) is plan 12.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from profile import (
    CGROUP_LIMITS,
    GUEST_REPO_ROOT,
    SCHEMA_VERSION,
    ProfileError,
    bootstrap_profile,
    persist_profile_revision,
    validate_profile,
)
from typing import Any, Callable

from config import Settings, get_settings
from errors import HarnessError
from fixtures import match_fixture
from harness import (
    ExecResult,
    create_environment,
    default_bootstrap_plan,
    destroy_job_environment,
    exec_command,
    images_differ,
    plan_for_image,
    replace_environment,
    wait_until_ready,
)
from heartbeat import with_heartbeat
from jobs import get_ledger

logger = logging.getLogger("killhub.discover")

ExecFn = Callable[..., ExecResult]

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class DiscoverResult:
    job_id: str
    resolved_commit: str
    profile: dict[str, Any]
    revision: int
    fixture_id: str | None
    environment_id: str
    replaced: bool = False
    sandbox_generation: int | None = None


class DiscoverError(Exception):
    def __init__(self, message: str, *, code: str = "discover_failed") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _span(
    job_id: str,
    name: str,
    *,
    settings: Settings,
    status: str = "ok",
    detail: dict[str, Any] | None = None,
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="span",
        message=name,
        payload={"span": name, "status": status, **(detail or {})},
    )


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


def _status(
    job_id: str,
    status: str,
    *,
    settings: Settings,
    step: str,
    progress: int,
    steps_completed: list[str] | None = None,
) -> None:
    fields: dict[str, Any] = {
        "status": status,
        "current_step": step,
        "progress": progress,
    }
    if steps_completed is not None:
        fields["steps_completed"] = steps_completed
    ledger = get_ledger(settings)
    ledger.update_job_fields(job_id, **fields)
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


def _exec(
    environment_id: str,
    cmd: list[str] | str,
    *,
    job_id: str,
    settings: Settings,
    exec_fn: ExecFn,
    timeout: float | None = None,
) -> ExecResult:
    return exec_fn(
        environment_id,
        cmd,
        job_id=job_id,
        settings=settings,
        timeout=timeout,
    )


def clone_and_resolve_commit(
    environment_id: str,
    *,
    job_id: str,
    github_url: str,
    commit: str | None,
    settings: Settings,
    exec_fn: ExecFn = exec_command,
) -> str:
    """Clone inside the sandbox and return the full resolved SHA (D62)."""
    # Portable guest shell (alpine has no bash by default).
    shell = ["sh", "-lc"]

    # Ensure git exists (install-phase egress allows package installs).
    probe = _exec(
        environment_id,
        [*shell, "command -v git || true"],
        job_id=job_id,
        settings=settings,
        exec_fn=exec_fn,
        timeout=30,
    )
    if "git" not in (probe.stdout or ""):
        install = with_heartbeat(
            job_id,
            settings=settings,
            label="installing git in sandbox",
            fn=lambda: _exec(
                environment_id,
                [
                    *shell,
                    "if command -v apt-get >/dev/null 2>&1; then "
                    "export DEBIAN_FRONTEND=noninteractive; "
                    "apt-get update -qq && apt-get install -y -qq git ca-certificates; "
                    "elif command -v apk >/dev/null 2>&1; then "
                    "apk add --no-cache git ca-certificates; "
                    "else echo 'no package manager' >&2; exit 1; fi",
                ],
                job_id=job_id,
                settings=settings,
                exec_fn=exec_fn,
                timeout=300,
            ),
        )
        if install.exit_code != 0:
            raise DiscoverError(
                f"failed to install git in sandbox: {(install.stderr or install.stdout)[:300]}",
                code="clone_prereq",
            )

    _exec(
        environment_id,
        [*shell, f"rm -rf {GUEST_REPO_ROOT} && mkdir -p {GUEST_REPO_ROOT}"],
        job_id=job_id,
        settings=settings,
        exec_fn=exec_fn,
        timeout=30,
    )

    if commit:
        clone_script = (
            f"set -eu; "
            f"git clone --filter=blob:none --no-checkout {json.dumps(github_url)} "
            f"{GUEST_REPO_ROOT}; "
            f"cd {GUEST_REPO_ROOT}; "
            f"git fetch --depth 1 origin {json.dumps(commit)}; "
            f"git checkout {json.dumps(commit)}"
        )
    else:
        clone_script = f"set -eu; git clone --depth 1 {json.dumps(github_url)} {GUEST_REPO_ROOT}"
    cloned = with_heartbeat(
        job_id,
        settings=settings,
        label="cloning repository",
        fn=lambda: _exec(
            environment_id,
            [*shell, clone_script],
            job_id=job_id,
            settings=settings,
            exec_fn=exec_fn,
            timeout=300,
        ),
    )
    if cloned.exit_code != 0:
        raise DiscoverError(
            f"sandbox clone failed: {(cloned.stderr or cloned.stdout)[:400]}",
            code="clone_failed",
        )

    sha_result = _exec(
        environment_id,
        [*shell, f"cd {GUEST_REPO_ROOT} && git rev-parse HEAD"],
        job_id=job_id,
        settings=settings,
        exec_fn=exec_fn,
        timeout=30,
    )
    sha = (sha_result.stdout or "").strip().splitlines()[-1].strip() if sha_result.stdout else ""
    if not _SHA_RE.match(sha):
        raise DiscoverError(
            f"could not resolve commit SHA (got {sha!r})",
            code="resolve_commit",
        )
    if commit and sha != commit:
        raise DiscoverError(
            f"resolved commit {sha} != requested pin {commit}",
            code="commit_mismatch",
        )
    return sha


def inspect_checkout(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings,
    exec_fn: ExecFn = exec_command,
) -> dict[str, Any]:
    """Collect cheap inspect signals from the cloned tree (in-guest)."""
    script = f"""
set -eu
cd {GUEST_REPO_ROOT}
echo '---TREE---'
find . -maxdepth 3 \\( -name node_modules -o -name .git \\) -prune -o -type f -print | head -n 200
echo '---PACKAGE_JSON---'
if [ -f package.json ]; then cat package.json; fi
echo '---PYPROJECT---'
if [ -f pyproject.toml ]; then head -n 200 pyproject.toml; fi
echo '---REQUIREMENTS---'
if [ -f requirements.txt ]; then head -n 40 requirements.txt; fi
echo '---README---'
if [ -f README.md ]; then head -n 60 README.md; elif [ -f README ]; then head -n 60 README; fi
echo '---MCP_FS---'
if [ -d src/filesystem ]; then ls src/filesystem | head -n 40; fi
if [ -f src/filesystem/package.json ]; then cat src/filesystem/package.json; fi
"""
    result = _exec(
        environment_id,
        ["sh", "-lc", script],
        job_id=job_id,
        settings=settings,
        exec_fn=exec_fn,
        timeout=120,
    )
    text = result.stdout or ""
    return {
        "exit_code": result.exit_code,
        "raw": text[:50_000],
        "has_package_json": (
            "---PACKAGE_JSON---" in text and "{" in text.split("---PACKAGE_JSON---", 1)[-1][:200]
        ),
        "has_filesystem_mcp": (
            "src/filesystem" in text or "@modelcontextprotocol/server-filesystem" in text
        ),
        "mentions_express": bool(re.search(r'"express"', text)),
        "mentions_mcp": ("modelcontextprotocol" in text.lower() or '"mcp"' in text.lower()),
        "python_mcp": python_mcp_signal(text),
    }


_PY_MCP_DEP = re.compile(r"""["']\s*(fastmcp|mcp)\s*(\[[^\]]*\])?\s*([<>=~!]=?[^"']*)?["']""", re.I)
_REQ_MCP = re.compile(r"^\s*(fastmcp|mcp)\s*(\[[^\]]*\])?\s*([<>=~!].*)?$", re.I | re.M)
_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SCRIPT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def _inspect_section(text: str, name: str) -> str:
    marker = f"---{name}---"
    if marker not in text:
        return ""
    rest = text.split(marker, 1)[1]
    nxt = re.search(r"^---[A-Z_]+---$", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def python_mcp_signal(text: str) -> dict[str, Any] | None:
    """Detect a Python MCP server (fastmcp / mcp dependency) and how to launch it.

    Launch preference: a ``[project.scripts]`` entry (one with "mcp" in its
    name, or the only one), else ``python -m <pkg>`` for a package with a
    ``__main__.py`` at ``src/<pkg>/`` or ``<pkg>/``. No launchable entry → None.
    """
    pyproject = _inspect_section(text, "PYPROJECT")
    reqs = _inspect_section(text, "REQUIREMENTS")
    tree = _inspect_section(text, "TREE")
    if not (_PY_MCP_DEP.search(pyproject) or _REQ_MCP.search(reqs)):
        return None
    launch: dict[str, str] | None = None
    block = re.search(r"^\[project\.scripts\]\s*\n((?:[^\[\n].*\n?)*)", pyproject, re.M)
    names = re.findall(r"^\s*([A-Za-z0-9_.-]+)\s*=", block.group(1), re.M) if block else []
    names = [n for n in names if _SCRIPT_RE.match(n)]
    script = next((n for n in names if "mcp" in n.lower()), names[0] if len(names) == 1 else None)
    if script:
        launch = {"kind": "script", "name": script}
    else:
        modules: list[str] = []
        for line in tree.splitlines():
            parts = line.strip().removeprefix("./").split("/")
            if parts[-1] != "__main__.py":
                continue
            if len(parts) == 3 and parts[0] == "src":
                modules.append(parts[1])
            elif len(parts) == 2:
                modules.append(parts[0])
        modules = sorted(m for m in set(modules) if _MODULE_RE.match(m))
        module = next((m for m in modules if "mcp" in m.lower()), modules[0] if modules else None)
        if module:
            launch = {"kind": "module", "name": module}
    if launch is None:
        return None
    files = {line.strip() for line in tree.splitlines()}
    return {
        **launch,
        "uv_lock": "./uv.lock" in files,
        "pyproject": bool(pyproject.strip()),
        "requirements": bool(reqs.strip()),
    }


def _python_mcp_profile(*, base: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    """git_mcp profile for a Python MCP server over stdio, installed with uv."""
    root = GUEST_REPO_ROOT
    install_uv = (
        "command -v uv >/dev/null 2>&1 || (curl -LsSf https://astral.sh/uv/install.sh "
        "| env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh)"
    )
    if signal.get("uv_lock"):
        # Exactly what the repo pinned; uv fetches a matching Python if needed.
        deps = _cmd(["uv", "sync", "--frozen", "--no-dev"], timeout=900, cwd=root)
    elif signal.get("pyproject"):
        deps = {
            "shell": "uv venv .venv && uv pip install --python .venv/bin/python .",
            "cwd": root,
            "timeout_seconds": 900,
        }
    else:
        deps = {
            "shell": (
                "uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt"
            ),
            "cwd": root,
            "timeout_seconds": 900,
        }
    if signal["kind"] == "script":
        argv = [f".venv/bin/{signal['name']}"]
        entry = signal["name"]
    else:
        argv = [".venv/bin/python", "-m", signal["name"]]
        entry = f"python -m {signal['name']}"
    launch = _cmd(argv, timeout=60, cwd=root)
    return {
        # Keep the same pinned source and sandbox policy as other runtime profiles.
        **base,
        "intent": "git_mcp",
        "runtime": "python",
        "packages": ["ca-certificates", "curl", "python3"],
        "commands": {
            "install": [{"shell": install_uv, "cwd": root, "timeout_seconds": 300}, deps],
            "run": [launch],
        },
        "processes": [],
        "probes": [{"name": "mcp-handshake", "type": "mcp_handshake", "timeout_seconds": 60}],
        "ports": [],
        "summary": f"Python MCP server from pinned checkout ({entry}, stdio)",
        "verification_target": "original_application",
        "mcp": {
            "transport": "stdio",
            "entrypoint": entry,
            "launch_command": launch,
            "cwd": root,
            "readiness": {"type": "mcp_handshake", "transport": "stdio", "timeout_seconds": 60},
        },
    }


def _cmd(argv: list[str], *, timeout: int = 120, cwd: str | None = None) -> dict[str, Any]:
    spec: dict[str, Any] = {"argv": argv, "timeout_seconds": timeout}
    if cwd:
        spec["cwd"] = cwd
    return spec


def infer_runtime_profile(
    *,
    github_url: str,
    commit: str,
    inspect: dict[str, Any],
    fixture: dict[str, Any] | None,
    oci_image: str,
) -> dict[str, Any]:
    """Heuristic discover (LLM optional later). Prefer fixture expected intent."""
    forbid_demo = bool((fixture or {}).get("forbid_demo_intent")) or bool(
        ((fixture or {}).get("policy") or {}).get("forbid_demo_intent")
    )
    expected = (fixture or {}).get("expected_intent")
    # Fixture may pin a different runtime OCI image to exercise replace (D36).
    if fixture and fixture.get("oci_image"):
        oci_image = str(fixture["oci_image"]).strip() or oci_image

    intent = expected
    python_mcp = inspect.get("python_mcp") if not (fixture or {}).get("mcp") else None
    if intent is None:
        if python_mcp:
            intent = "git_mcp"
        elif inspect.get("has_filesystem_mcp") or (
            inspect.get("mentions_mcp") and "servers" in github_url
        ):
            intent = "git_mcp"
        elif inspect.get("has_package_json") and (
            inspect.get("mentions_express") or "getting-started" in github_url
        ):
            intent = "webapp"
        elif forbid_demo:
            raise DiscoverError(
                "no git_mcp/webapp fit and forbid_demo_intent=true",
                code="setup_failed_fixture",
            )
        else:
            intent = "demo"

    if forbid_demo and intent == "demo":
        raise DiscoverError(
            "fixture forbids demo intent",
            code="setup_failed_fixture",
        )

    base = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "type": "github_repo",
            "url": github_url,
            "commit": commit,
            "ref": (fixture or {}).get("ref") or "HEAD",
        },
        "os_image": "linux",
        "oci_image": oci_image,
        "workdir": GUEST_REPO_ROOT,
        "services": [],
        # These fields declare the policy requested for the workload.
        "network_mode": "install",
        "cgroup_limits": dict(CGROUP_LIMITS),
    }

    if intent == "git_mcp" and python_mcp:
        return _python_mcp_profile(base=base, signal=python_mcp)

    if intent == "git_mcp":
        mcp_meta = (fixture or {}).get("mcp") or {
            "transport": "stdio",
            "entrypoint": "src/filesystem",
            "workdir_relative": "src/filesystem",
            "launch_bin": "dist/index.js",
        }
        workdir_rel = str(mcp_meta.get("workdir_relative") or "src/filesystem")
        guest_workdir = f"{GUEST_REPO_ROOT}/{workdir_rel}"
        launch_bin = str(mcp_meta.get("launch_bin") or "dist/index.js")
        return {
            **base,
            "intent": "git_mcp",
            "runtime": "node",
            "workdir": guest_workdir,
            # Fixture requires Node >= 24 for @modelcontextprotocol/server-filesystem.
            "packages": ["ca-certificates", "curl", "python3"],
            "commands": {
                "install": [
                    {
                        "shell": (
                            "curl -fsSL https://deb.nodesource.com/setup_24.x | bash - "
                            "&& apt-get install -y -qq nodejs"
                        ),
                        "cwd": guest_workdir,
                        "timeout_seconds": 600,
                    },
                    _cmd(["npm", "install"], timeout=600, cwd=guest_workdir),
                    _cmd(["npm", "run", "build"], timeout=600, cwd=guest_workdir),
                ],
                "run": [
                    _cmd(
                        ["node", launch_bin, GUEST_REPO_ROOT],
                        timeout=60,
                        cwd=guest_workdir,
                    ),
                ],
            },
            "processes": [
                {
                    "name": "mcp-filesystem",
                    "command": _cmd(
                        ["node", launch_bin, GUEST_REPO_ROOT],
                        timeout=3600,
                        cwd=guest_workdir,
                    ),
                    "supervise": "restart",
                    "ready_after_seconds": 1,
                }
            ],
            "ports": [],
            "probes": [{"name": "mcp-handshake", "type": "mcp_handshake", "timeout_seconds": 30}],
            "summary": "MCP filesystem server from pinned checkout (stdio)",
            "verification_target": "original_application",
            "mcp": {
                **(
                    {"security_assessment": mcp_meta["security_assessment"]}
                    if "security_assessment" in mcp_meta
                    else {}
                ),
                "transport": "stdio",
                "entrypoint": mcp_meta.get("entrypoint") or "src/filesystem",
                "launch_command": _cmd(
                    ["node", launch_bin, GUEST_REPO_ROOT],
                    timeout=60,
                    cwd=guest_workdir,
                ),
                "cwd": guest_workdir,
                "readiness": {
                    "type": "mcp_handshake",
                    "transport": "stdio",
                    "timeout_seconds": 30,
                },
            },
        }

    if intent == "webapp":
        return {
            **base,
            "intent": "webapp",
            "runtime": "node",
            # The offline HTTP probe requires a client installed before egress is closed.
            "packages": ["nodejs", "npm", "curl"],
            "commands": {
                "install": [_cmd(["npm", "install"], timeout=600, cwd=GUEST_REPO_ROOT)],
                "run": [_cmd(["npm", "start"], timeout=60, cwd=GUEST_REPO_ROOT)],
            },
            "processes": [
                {
                    "name": "web",
                    "command": _cmd(["npm", "start"], timeout=3600, cwd=GUEST_REPO_ROOT),
                    "supervise": "restart",
                    "ready_after_seconds": 2,
                    "ready_probe": "http-root",
                }
            ],
            "ports": [5000, 3000],
            "summary": "Node webapp from pinned getting-started checkout",
            "verification_target": "original_application",
            "probes": [
                {
                    "name": "http-root",
                    "type": "http",
                    "url": "http://127.0.0.1:5000/",
                    "expected_statuses": [200, 301, 302],
                    "timeout_seconds": 10,
                }
            ],
        }

    # demo
    demo_argv = ["python3", "-m", "http.server", "8000", "--bind", "127.0.0.1"]
    return {
        **base,
        "intent": "demo",
        "runtime": "python",
        "packages": ["python3"],
        "commands": {
            "install": [],
            "run": [_cmd(demo_argv, timeout=60, cwd=GUEST_REPO_ROOT)],
        },
        "processes": [
            {
                "name": "demo-http",
                "command": _cmd(demo_argv, timeout=3600, cwd=GUEST_REPO_ROOT),
                "supervise": "restart",
                "ready_after_seconds": 1,
            }
        ],
        "ports": [8000],
        "summary": "No webapp or MCP fit was found. Generated a minimal HTTP demo.",
        "verification_target": "generated_demo",
        "probes": [
            {
                "name": "http-root",
                "type": "http",
                "url": "http://127.0.0.1:8000/",
                "expected_statuses": [200],
                "timeout_seconds": 10,
            }
        ],
    }


def load_prompt(name: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")


def discover_runtime_profile(
    job_id: str,
    *,
    settings: Settings | None = None,
    exec_fn: ExecFn = exec_command,
    create: bool = True,
    destroy_on_failure: bool = True,
) -> DiscoverResult:
    """
    Full plan-loop steps 0–3 without install/readiness (D36).

    Bootstrap create → in-sandbox clone/inspect → runtime profile revision.
    """
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise DiscoverError(f"unknown job_id: {job_id}", code="not_found")

    fixture = match_fixture(job.github_url)
    catalog_pin = str(fixture["commit"]) if fixture and fixture.get("commit") else None
    # A queued fixture's recorded commit takes precedence over the current catalog.
    # If the fixture changed, its current build metadata may no longer fit that commit.
    if job.resolved_commit is not None and catalog_pin and job.resolved_commit != catalog_pin:
        raise DiscoverError("Fixture pin changed after admission", code="fixture_pin_changed")
    pin = job.resolved_commit if job.resolved_commit is not None else catalog_pin
    if pin is not None and not _SHA_RE.fullmatch(pin):
        raise DiscoverError("Invalid recorded Git commit", code="invalid_commit")
    oci_image = (cfg.msb_default_image or "debian").strip()

    # Trusted prompts are host-owned (never submitted-repo AGENTS.md).
    _ = load_prompt("discover_environment")
    _ = load_prompt("validate_environment_spec")

    boot = bootstrap_profile(
        github_url=job.github_url,
        oci_image=oci_image,
        ref=(fixture or {}).get("ref"),
    )
    validate_profile(boot, phase="bootstrap")
    boot_rev = persist_profile_revision(job_id, boot, phase="bootstrap", settings=cfg)
    _span(
        job_id,
        "bootstrap_profile",
        settings=cfg,
        detail={"revision": boot_rev.revision},
    )

    environment_id = job.sandbox_id
    created_here = False
    try:
        if create and not environment_id:
            _status(
                job_id,
                "provisioning",
                settings=cfg,
                step="bootstrap sandbox create",
                progress=15,
                steps_completed=["pending"],
            )
            _span(job_id, "bootstrap_create", settings=cfg, status="start")
            # create_environment heartbeats msb create + guest ready-wait.
            gen = create_environment(
                job_id,
                default_bootstrap_plan(cfg),
                settings=cfg,
            )
            environment_id = gen.environment_id
            created_here = True
            wait_until_ready(environment_id, settings=cfg, job_id=job_id)
            _span(
                job_id,
                "bootstrap_create",
                settings=cfg,
                detail={"environment_id": environment_id, "generation": gen.generation},
            )
        elif environment_id:
            wait_until_ready(environment_id, settings=cfg, job_id=job_id)
        else:
            raise DiscoverError(
                "no sandbox; create=True required for bootstrap discover",
                code="no_sandbox",
            )

        assert environment_id is not None
        _status(
            job_id,
            "analyzing",
            settings=cfg,
            step="clone and inspect in sandbox",
            progress=35,
            steps_completed=["pending", "provisioning"],
        )
        _span(job_id, "clone_inspect", settings=cfg, status="start")
        resolved = clone_and_resolve_commit(
            environment_id,
            job_id=job_id,
            github_url=job.github_url,
            commit=pin,
            settings=cfg,
            exec_fn=exec_fn,
        )
        ledger.update_job_fields(job_id, resolved_commit=resolved)
        _log(
            job_id,
            f"resolved_commit={resolved}",
            settings=cfg,
            kind="discover",
            resolved_commit=resolved,
            fixture_id=(fixture or {}).get("id"),
        )

        inspect = inspect_checkout(
            environment_id,
            job_id=job_id,
            settings=cfg,
            exec_fn=exec_fn,
        )
        _span(
            job_id,
            "clone_inspect",
            settings=cfg,
            detail={"files_sampled": inspect.get("has_package_json")},
        )

        _status(
            job_id,
            "planning",
            settings=cfg,
            step="infer runtime profile",
            progress=55,
            steps_completed=["pending", "provisioning", "analyzing"],
        )
        _span(job_id, "infer_profile", settings=cfg, status="start")
        try:
            runtime = infer_runtime_profile(
                github_url=job.github_url,
                commit=resolved,
                inspect=inspect,
                fixture=fixture,
                oci_image=oci_image,
            )
        except DiscoverError as exc:
            if exc.code == "setup_failed_fixture":
                # Record verification evidence but stay non-terminal so the
                # finalizer can SCA + destroy + set failed (D37, D53, D61).
                verification = {
                    "kind": "setup_failed",
                    "original_failure": {
                        "step": "discover",
                        "summary": exc.message,
                    },
                }
                ledger.append_event(
                    job_id,
                    typ="log",
                    message="setup_failed fixture — awaiting finalize reclaim",
                    payload={"reason": "setup_failed_fixture"},
                )
                ledger.update_job_fields(
                    job_id,
                    current_step="setup_failed (fixture) — finalizing",
                    error=exc.message,
                    verification=verification,
                )
            raise

        validate_profile(runtime, phase="runtime")
        rev = persist_profile_revision(job_id, runtime, phase="runtime", settings=cfg)
        _span(
            job_id,
            "infer_profile",
            settings=cfg,
            detail={
                "revision": rev.revision,
                "intent": runtime["intent"],
                "oci_image": runtime.get("oci_image"),
            },
        )
        _log(
            job_id,
            f"runtime profile revision {rev.revision} intent={runtime['intent']}",
            settings=cfg,
            kind="discover",
            intent=runtime["intent"],
            revision=rev.revision,
            storage_path=rev.storage_path,
        )

        replaced = False
        runtime_image = str(runtime.get("oci_image") or oci_image).strip()
        if images_differ(oci_image, runtime_image):
            _status(
                job_id,
                "provisioning",
                settings=cfg,
                step=f"replace sandbox → {runtime_image}",
                progress=60,
                steps_completed=[
                    "pending",
                    "provisioning",
                    "analyzing",
                    "planning",
                ],
            )
            _span(job_id, "sandbox_replace", settings=cfg, status="start")
            new_gen = replace_environment(
                job_id,
                plan_for_image(runtime_image, settings=cfg),
                settings=cfg,
                reclone=True,
            )
            environment_id = new_gen.environment_id
            replaced = True
            _span(
                job_id,
                "sandbox_replace",
                settings=cfg,
                detail={
                    "generation": new_gen.generation,
                    "image": runtime_image,
                    "environment_id": environment_id,
                },
            )
        else:
            _log(
                job_id,
                f"same oci_image={runtime_image}; continue in place",
                settings=cfg,
                kind="sandbox_replace",
                skipped=True,
                image=runtime_image,
            )

        job_now = ledger.get_job(job_id)
        gen_no = job_now.current_sandbox_generation if job_now else None

        _status(
            job_id,
            "planning",
            settings=cfg,
            step="runtime profile validated",
            progress=65,
            steps_completed=["pending", "provisioning", "analyzing", "planning"],
        )

        return DiscoverResult(
            job_id=job_id,
            resolved_commit=resolved,
            profile=runtime,
            revision=rev.revision,
            fixture_id=(fixture or {}).get("id"),
            environment_id=environment_id,
            replaced=replaced,
            sandbox_generation=gen_no,
        )
    except Exception as exc:
        # Controlled setup_failed fixtures keep the sandbox alive for later
        # evidence / plan-14 readiness honesty (D53, D37) — destroy is finalizer-owned.
        skip_destroy = isinstance(exc, DiscoverError) and exc.code == "setup_failed_fixture"
        if destroy_on_failure and created_here and not skip_destroy:
            try:
                destroy_job_environment(job_id, settings=cfg)
            except HarnessError:
                logger.exception("destroy after discover failure failed")
        if isinstance(exc, (DiscoverError, ProfileError, HarnessError)):
            raise
        raise DiscoverError(str(exc), code="discover_failed") from exc


def discover_fixture_profile(
    fixture_id: str,
    *,
    settings: Settings | None = None,
    exec_fn: ExecFn | None = None,
) -> DiscoverResult:
    """Create a job for a pinned fixture and run bootstrap discover."""
    from fixtures import require_fixture
    from service import create_job

    cfg = settings or get_settings()
    fixture = require_fixture(fixture_id)
    job = create_job(str(fixture["github_url"]), settings=cfg)
    return discover_runtime_profile(
        job.job_id,
        settings=cfg,
        exec_fn=exec_fn or exec_command,
        create=True,
    )
