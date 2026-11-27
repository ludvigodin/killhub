"""environment_profile.json schema + bootstrap/runtime IO (D51, D36, D64)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from config import Settings, get_settings
from errors import HarnessError
from git_url import parse_public_git_url
from jobs import get_ledger
from models import ProfilePhase

SCHEMA_VERSION = "1"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "environment_profile.v1.json"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

RUNTIME_INTENTS = frozenset({"git_mcp", "webapp", "demo"})
GUEST_REPO_ROOT = "/tmp/killhub/repo"

# Requested workload limits (D72), separate from evidence of guest enforcement.
CGROUP_LIMITS = {
    "memory_max": "512M",
    "memory_swap_max": "0",
    "pids_max": 64,
    "cpu_max": "100000 100000",
}


class ProfileError(Exception):
    def __init__(self, message: str, *, code: str = "profile_invalid") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _runtime_validator() -> Draft202012Validator:
    return Draft202012Validator(load_schema(), format_checker=FormatChecker())


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
        if "commands" in profile:
            raise ProfileError("runtime commands are invalid on clone-only bootstrap profiles")
        if profile.get("install_commands") not in ([], None):
            # Allow missing; if present must be empty for bootstrap.
            if profile.get("install_commands"):
                raise ProfileError("bootstrap profile must not install packages")
        if profile.get("run_commands") not in ([], None):
            if profile.get("run_commands"):
                raise ProfileError("bootstrap profile must not run the app")
        return profile

    if not isinstance(intent, str) or intent not in RUNTIME_INTENTS:
        raise ProfileError(
            "runtime intent must be git_mcp|webapp|demo",
            code="intent",
        )
    source = profile.get("source")
    commit = source.get("commit") if isinstance(source, dict) else None
    if not isinstance(commit, str) or not _SHA_RE.fullmatch(commit):
        raise ProfileError(
            "source.commit must be a full 40-char SHA (D62)",
            code="missing_commit",
        )

    error = next(_runtime_validator().iter_errors(profile), None)
    if error is not None:
        # Validation errors can include profile content. Return the rule and path only.
        raise ProfileError(f"runtime profile failed {error.validator} at {error.json_path}")

    if source["type"] == "github_repo":
        try:
            parsed = parse_public_git_url(source.get("url", ""))
        except ValueError as exc:
            raise ProfileError("GitHub runtime profiles require a public HTTPS repository") from exc
        if parsed.host != "github.com":
            raise ProfileError("GitHub runtime profiles require a github.com repository")

    if intent == "git_mcp":
        mcp = profile["mcp"]
        if mcp["readiness"]["transport"] != mcp["transport"]:
            raise ProfileError("MCP readiness must use the declared transport")
    elif not profile["probes"]:
        raise ProfileError(f"{intent} profile requires a readiness probe")

    return profile


def _adapt_stored_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Translate the former Git runtime layout before applying canonical validation."""
    source = profile.get("source")
    if "commands" in profile or not isinstance(source, dict) or source.get("type") != "git":
        return profile

    adapted = dict(profile)
    adapted["source"] = {**source, "type": "github_repo"}
    adapted["commands"] = {
        "install": adapted.pop("install_commands", None),
        "run": adapted.pop("run_commands", None),
    }
    # The historical runtime launched each declared process once if unspecified.
    processes = adapted.get("processes")
    if isinstance(processes, list):
        adapted["processes"] = [
            {"supervise": "oneshot", **process} if isinstance(process, dict) else process
            for process in processes
        ]

    healthcheck = adapted.pop("healthcheck", None)
    probes = adapted.get("probes") or healthcheck or []
    if isinstance(probes, dict):
        probes = [probes]
    if isinstance(probes, list):
        normalized = []
        for probe in probes:
            if isinstance(probe, dict):
                probe = dict(probe)
                if probe.get("url"):
                    probe.setdefault("type", "http")
                if "accept" in probe:
                    probe.setdefault("expected_statuses", probe.pop("accept"))
            normalized.append(probe)
        probes = normalized
    adapted["probes"] = probes
    adapted.setdefault("network_mode", "install")
    adapted.setdefault("cgroup_limits", dict(CGROUP_LIMITS))
    # Keep historical failure context on the receipt side of the boundary.
    adapted.pop("original_failure", None)
    return adapted


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


def assert_runtime_ready_for_provision(
    profile: dict[str, Any], *, stored: bool = False
) -> dict[str, Any]:
    """Validate the executable view, adapting old revisions only after ledger reads."""
    try:
        executable = (
            _adapt_stored_profile(profile) if stored and isinstance(profile, dict) else profile
        )
        return validate_profile(executable, phase="runtime")
    except ProfileError as exc:
        raise HarnessError(
            f"runtime profile blocks provision: {exc.message}",
            code="profile_blocks_provision",
        ) from exc
