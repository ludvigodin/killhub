"""Randomized canary credentials for Plane 2 (D44). Never log plaintext to SSE."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Collection

from config import Settings, get_settings
from errors import HarnessError

logger = logging.getLogger("killhub.canaries")

# Paths where planted canaries are expected (not unexpected hits).
_PLANTED_PATH_PREFIXES = ("/tmp/killhub/canaries/",)


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
    exec_command(
        environment_id,
        ["mkdir", "-p", "/tmp/killhub/canaries"],
        job_id=job_id,
        settings=cfg,
        cli=cli,
        timeout=30,
    )
    for guest_path, value in canaries.files.items():
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


def _is_planted_path(path: str) -> bool:
    return any(path.startswith(p) or path == p.rstrip("/") for p in _PLANTED_PATH_PREFIXES)


def scan_canaries(
    environment_id: str,
    *,
    job_id: str,
    settings: Settings | None = None,
    cli: Any = None,
    probe_sessions_exclude: Collection[str] | None = None,
) -> dict[str, Any]:
    """
    Scan guest for unexpected canary material (D44, D65).

    Never emits canary plaintext on the job stream. Deliberate probe sessions
    listed in `probe_sessions_exclude` are ignored when tagging findings.
    """
    from harness import exec_command

    cfg = settings or get_settings()
    ledger = None
    try:
        from jobs import get_ledger

        ledger = get_ledger(cfg)
    except Exception:  # noqa: BLE001
        ledger = None

    record = load_canaries(job_id, settings)
    if record is None:
        return {
            "status": "missing",
            "claim": "incomplete",
            "reason": "no_canary_record",
            "known_ids": [],
            "unexpected_hits": [],
            "hit_count": 0,
        }

    exclude = set(probe_sessions_exclude or ())

    # Deliberate tagged read — proves scanner exclusion path (D65).
    deliberate = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            "export KILLHUB_PROBE_SESSION=containment_canary_deliberate; "
            "head -c 8 /tmp/killhub/canaries/token >/dev/null 2>&1; echo deliberate_ok",
        ],
        job_id=job_id,
        settings=cfg,
        cli=cli,
        timeout=30,
    )
    deliberate_ok = "deliberate_ok" in (deliberate.stdout or "")

    # Search guest for planted values outside planted paths. Pass fingerprints +
    # values via a short-lived python scanner that only prints path ids.
    values = list(record.files.values()) + list(record.env.values())
    # Encode values as b64 list so shell never sees raw secrets in argv logs twice.
    import base64

    payload_b64 = base64.b64encode(json.dumps(values).encode("utf-8")).decode("ascii")
    planted_paths = list(record.files.keys())
    planted_b64 = base64.b64encode(json.dumps(planted_paths).encode("utf-8")).decode("ascii")

    scanner = f"""
import base64, json, os, sys
values = json.loads(base64.b64decode({payload_b64!r}).decode())
planted = set(json.loads(base64.b64decode({planted_b64!r}).decode()))
hits = []
roots = ["/tmp", "/var/tmp", "/home", "/root"]
skip_prefixes = tuple(planted) + ("/tmp/killhub/canaries/",)
for root in roots:
    if not os.path.isdir(root):
        continue
    for dirpath, dirnames, filenames in os.walk(root):
        # Do not descend into planted canary dir.
        dirnames[:] = [
            d for d in dirnames
            if not os.path.join(dirpath, d).startswith("/tmp/killhub/canaries")
        ]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if any(path == p or path.startswith(p) for p in skip_prefixes):
                continue
            try:
                if os.path.getsize(path) > 2_000_000:
                    continue
                data = open(path, "rb").read()
            except Exception:
                continue
            for v in values:
                raw = v.encode("utf-8", errors="ignore")
                if raw and raw in data:
                    hits.append(path)
                    break
print(json.dumps({{"hits": hits[:50], "scanned": True}}))
"""
    # Prefer writing the scanner via stdin so msb exec argv stays small/stable.
    result = exec_command(
        environment_id,
        [
            "sh",
            "-lc",
            "if ! command -v python3 >/dev/null 2>&1; then "
            'echo \'{"hits":[],"scanned":false,"error":"python3_missing"}\'; '
            "exit 3; fi; "
            "python3 - <<'KILLHUB_CANARY_SCAN'\n"
            f"{scanner}\n"
            "KILLHUB_CANARY_SCAN",
        ],
        job_id=job_id,
        settings=cfg,
        cli=cli,
        timeout=120,
    )

    unexpected: list[str] = []
    status = "ok"
    detail = ""
    combined_out = (result.stdout or "") + (result.stderr or "")
    if result.exit_code == 3 or "python3_missing" in combined_out:
        status = "tooling_missing"
        detail = "python3_missing"
    elif result.exit_code != 0:
        status = "error"
        detail = (result.stderr or result.stdout or "")[:200]
    else:
        try:
            # Take last JSON line.
            parsed = {}
            for line in (result.stdout or "").splitlines():
                line = line.strip()
                if line.startswith("{"):
                    parsed = json.loads(line)
            if parsed.get("error") == "python3_missing":
                status = "tooling_missing"
                detail = "python3_missing"
            for path in parsed.get("hits") or []:
                if not _is_planted_path(str(path)):
                    unexpected.append(str(path))
        except json.JSONDecodeError:
            status = "error"
            detail = "scanner_json_parse_failed"

    # Emit findings for unexpected hits only — fingerprints/paths, never plaintext.
    if ledger is not None and unexpected:
        # If the only "session" context is excluded deliberate probes, still report
        # file hits (file hits are not session-tagged).
        for path in unexpected:
            ledger.append_event(
                job_id,
                typ="finding",
                message="unexpected canary material detected",
                payload={
                    "source": "canary",
                    "code": "canary_unexpected_hit",
                    "severity": "high",
                    "path": path,
                    # Fingerprint of path string only — not secret material.
                    "path_fp": _fp(path),
                    "probe_sessions_excluded": sorted(exclude),
                },
            )

    return {
        "status": status,
        "claim": "ok" if status == "ok" else "incomplete",
        "known_ids": sorted(record.fingerprints.keys()),
        "unexpected_hits": unexpected,
        "hit_count": len(unexpected),
        "deliberate_probe_ok": deliberate_ok,
        "detail": detail,
        "probe_sessions_excluded": sorted(exclude),
    }


def network_probe(
    environment_id: str,
    *,
    job_id: str,
    phase: str = "verify",
    settings: Settings | None = None,
    cli: Any = None,
) -> dict[str, Any]:
    """Delegate to containment network matrix (D58, D65)."""
    from containment import network_probe as _containment_network_probe

    return _containment_network_probe(
        environment_id,
        job_id=job_id,
        phase=phase,
        settings=settings,
        cli=cli,
    )
