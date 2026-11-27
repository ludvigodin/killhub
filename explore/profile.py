"""environment_profile.json schema + bootstrap/runtime IO (D51, D36, D64)."""

from __future__ import annotations

import json
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
    """Killhub-owned bootstrap profile — clone-only, no install/run (D36)."""
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


def _require_command_specs(value: Any, *, field: str) -> None:
    if not isinstance(value, list):
        raise ProfileError(f"{field} must be an array")
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise ProfileError(f"{field}[{i}] must be an object")
        if "argv" not in item and "shell" not in item:
            raise ProfileError(f"{field}[{i}] requires argv or shell")
        if "timeout_seconds" not in item:
            raise ProfileError(f"{field}[{i}] requires timeout_seconds")


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

    _require_command_specs(profile["install_commands"], field="install_commands")
    _require_command_specs(profile["run_commands"], field="run_commands")

    if not isinstance(profile["services"], list):
        raise ProfileError("services must be an array")
    if not isinstance(profile["packages"], list):
        raise ProfileError("packages must be an array")
    if not isinstance(profile["processes"], list):
        raise ProfileError("processes must be an array")
    if not isinstance(profile["ports"], list):
        raise ProfileError("ports must be an array")

    if intent == "git_mcp":
        mcp = _require(profile, "mcp", ctx="git_mcp")
        if not isinstance(mcp, dict):
            raise ProfileError("mcp must be an object")
        transport = mcp.get("transport")
        if transport not in {"stdio", "streamable_http"}:
            raise ProfileError("mcp.transport must be stdio|streamable_http")
        launch = mcp.get("launch_command")
        if not isinstance(launch, dict):
            raise ProfileError("mcp.launch_command is required")
        if "argv" not in launch and "shell" not in launch:
            raise ProfileError("mcp.launch_command requires argv or shell")
        if "timeout_seconds" not in launch:
            raise ProfileError("mcp.launch_command requires timeout_seconds")
        readiness = mcp.get("readiness")
        if not isinstance(readiness, dict) or readiness.get("type") != "mcp_handshake":
            raise ProfileError("mcp.readiness.type must be mcp_handshake")
        if transport == "streamable_http" and not mcp.get("url"):
            raise ProfileError("mcp.url required for streamable_http")

    if intent in {"webapp", "demo"}:
        probes = profile.get("probes") or profile.get("healthcheck")
        if not probes:
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
