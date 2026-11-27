"""Randomized canary credentials for Plane 2 (D44). Never log plaintext to SSE."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from errors import HarnessError

logger = logging.getLogger("killhub.canaries")


@dataclass(frozen=True)
class CanarySet:
    job_id: str
    env: dict[str, str]
    files: dict[str, str]  # guest_path → plaintext
    fingerprints: dict[str, str]  # id → sha256 hex

    def public_summary(self) -> dict[str, Any]:
        """Safe for SSE / lifecycle payloads — fingerprints only."""
        return {
            "planted": True,
            "ids": sorted(self.fingerprints.keys()),
            "fingerprints": dict(self.fingerprints),
        }


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_canaries(job_id: str) -> CanarySet:
    """Plant-shaped canaries that are not real Killhub secrets."""
    token = secrets.token_urlsafe(32)
    fake_key = f"CKEY_{secrets.token_hex(20)}"
    fake_password = secrets.token_urlsafe(24)
    env = {
        "KILLHUB_CANARY_TOKEN": token,
        "KILLHUB_CANARY_AWS_SECRET_ACCESS_KEY": fake_key,
        "KILLHUB_CANARY_DB_PASSWORD": fake_password,
    }
    files = {
        "/tmp/killhub/canaries/token": token,
        "/tmp/killhub/canaries/aws_secret": fake_key,
    }
    fingerprints = {
        "env:KILLHUB_CANARY_TOKEN": _fp(token),
        "env:KILLHUB_CANARY_AWS_SECRET_ACCESS_KEY": _fp(fake_key),
        "env:KILLHUB_CANARY_DB_PASSWORD": _fp(fake_password),
        "file:/tmp/killhub/canaries/token": _fp(token),
        "file:/tmp/killhub/canaries/aws_secret": _fp(fake_key),
    }
    return CanarySet(job_id=job_id, env=env, files=files, fingerprints=fingerprints)


def canary_store_path(job_id: str, settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    base = Path(getattr(cfg, "canary_storage", None) or "./storage/canaries")
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / base
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{job_id}.json"


def persist_canaries(canaries: CanarySet, settings: Settings | None = None) -> Path:
    """Plane-1 only store (includes plaintext for later scan). Never stream this file."""
    path = canary_store_path(canaries.job_id, settings)
    path.write_text(json.dumps(asdict(canaries), indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


def load_canaries(job_id: str, settings: Settings | None = None) -> CanarySet | None:
    path = canary_store_path(job_id, settings)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return CanarySet(
        job_id=data["job_id"],
        env=dict(data["env"]),
        files=dict(data["files"]),
        fingerprints=dict(data["fingerprints"]),
    )


def plant_file_canaries(
    environment_id: str,
    canaries: CanarySet,
    *,
    job_id: str,
    settings: Settings | None = None,
    cli: Any = None,
) -> None:
    """Write canary files inside the guest via exec (no plaintext in SSE)."""
    from harness import exec_command

    cfg = settings or get_settings()
    # Create dir then write each file with a here-doc via printf/base64 to avoid shell history.
    exec_command(
        environment_id,
        ["mkdir", "-p", "/tmp/killhub/canaries"],
        job_id=job_id,
        settings=cfg,
        cli=cli,
        timeout=30,
    )
    for guest_path, value in canaries.files.items():
        # Use python if available, else printf.
        b64 = __import__("base64").b64encode(value.encode("utf-8")).decode("ascii")
        script = (
            'python3 -c "import base64,pathlib; '
            f'pathlib.Path({guest_path!r}).write_bytes(base64.b64decode({b64!r}))" '
            f"2>/dev/null || printf '%s' '{b64}' | base64 -d > {guest_path}"
        )
        result = exec_command(
            environment_id,
            ["sh", "-c", script],
            job_id=job_id,
            settings=cfg,
            cli=cli,
            timeout=30,
        )
        if result.exit_code != 0:
            raise HarnessError(
                f"failed to plant canary file {guest_path}",
                code="canary_plant_failed",
            )


def scan_canaries(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings | None = None,
    cli: Any = None,
) -> dict[str, Any]:
    """
    Stub for step 15 — full canary exfil scan.

    Returns an incomplete claim so callers do not invent success (D47/D66).
    """
    _ = environment_id, settings, cli
    record = load_canaries(job_id, settings)
    return {
        "status": "stub",
        "claim": "incomplete",
        "reason": "canary scan lands in step 15",
        "known_ids": sorted(record.fingerprints.keys()) if record else [],
    }


def network_probe(
    environment_id: str,
    *,
    job_id: str,
    phase: str = "install",
    settings: Settings | None = None,
    cli: Any = None,
) -> dict[str, Any]:
    """
    Stub for step 15 containment / network_probe matrix (D58, D65).

    Does not claim policy_denied without evidence.
    """
    _ = environment_id, job_id, settings, cli
    return {
        "status": "stub",
        "claim": "incomplete",
        "phase": phase,
        "reason": "network_probe matrix lands in step 15",
        "dimensions": [
            "timeout_enforcement",
            "host_access_denied",
            "sibling_access_denied",
            "host_liveness",
        ],
    }
