"""D60 host-path resolution for harness copy_in / copy_out."""

from __future__ import annotations

import os
from pathlib import Path

from config import Settings, get_settings
from errors import HarnessError

# Logical helper ids → relative paths under HELPERS_ROOT.
HELPER_CATALOG: dict[str, str] = {
    "env_probe": "env_probe.sh",
}

ARTIFACT_KINDS = frozenset({"screenshot", "lockfile", "log", "artifact"})

FORBIDDEN_ENV_KEYS = frozenset(
    {
        "VULTR_API_KEY",
        "VULTR_INFERENCE_API_KEY",
        "INTERNAL_API_TOKEN",
        "OPENCODE_API_KEY",
        "OPENCODE_CONFIG",
    }
)


def helpers_root(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    root = Path(cfg.helpers_root)
    if not root.is_absolute():
        root = Path(__file__).resolve().parent / root
    return root.resolve()


def _under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_copy_in_source(
    helper_ref: str,
    *,
    settings: Settings | None = None,
) -> Path:
    """
    Map a logical helper id or allowlisted relative path to a host file (D60).

    Rejects absolute paths, `~`, `..`, symlink escape, and non-regular files.
    """
    raw = (helper_ref or "").strip()
    if not raw:
        raise HarnessError("helper ref is required", code="path_forbidden")
    if raw.startswith("/") or raw.startswith("~") or raw.startswith("file:"):
        raise HarnessError(
            "arbitrary host paths are not allowed for copy_in",
            code="path_forbidden",
        )
    if len(raw) >= 2 and raw[1] == ":":
        raise HarnessError(
            "arbitrary host paths are not allowed for copy_in",
            code="path_forbidden",
        )

    rel = HELPER_CATALOG.get(raw, raw)
    if any(p == ".." for p in Path(rel).parts):
        raise HarnessError("path traversal rejected", code="path_forbidden")

    root = helpers_root(settings)
    joined = root / rel
    if not _under_root(joined, root):
        raise HarnessError("helper path escapes helpers root", code="path_forbidden")

    real = Path(os.path.realpath(joined))
    if not _under_root(real, root):
        raise HarnessError("symlink escape rejected", code="path_forbidden")
    if not real.is_file() or real.is_symlink():
        # After realpath, symlink nodes are resolved; require a regular file.
        if not real.is_file():
            raise HarnessError(
                f"helper not found or not a regular file: {raw}",
                code="path_forbidden",
            )
    return real


def validate_guest_path(guest_path: str) -> str:
    """Guest paths: no `..`; must be absolute under /tmp/killhub, /tmp, or /workspace."""
    raw = (guest_path or "").strip()
    if not raw:
        raise HarnessError("guest path is required", code="path_forbidden")
    if "\x00" in raw:
        raise HarnessError("invalid guest path", code="path_forbidden")
    if any(p == ".." for p in Path(raw).parts):
        raise HarnessError("guest path traversal rejected", code="path_forbidden")
    if not raw.startswith("/"):
        raise HarnessError("guest path must be absolute", code="path_forbidden")
    allowed_prefixes = ("/tmp/killhub/", "/workspace/", "/tmp/")
    if not any(raw == p.rstrip("/") or raw.startswith(p) for p in allowed_prefixes):
        raise HarnessError(
            "guest path must be under /tmp/killhub, /tmp, or /workspace",
            code="path_forbidden",
        )
    return raw


def resolve_copy_out_dest(
    job_id: str,
    artifact_kind: str,
    *,
    filename: str,
    settings: Settings | None = None,
) -> Path:
    """Server-selected per-job artifact destination (D60)."""
    cfg = settings or get_settings()
    kind = (artifact_kind or "").strip().lower()
    if kind not in ARTIFACT_KINDS:
        raise HarnessError(
            f"unknown artifact kind: {artifact_kind}",
            code="path_forbidden",
        )
    if any(p == ".." for p in Path(job_id).parts) or not job_id or "/" in job_id:
        # job ids are UUIDs; reject path-shaped ids
        if "/" in job_id or ".." in job_id:
            raise HarnessError("invalid job_id for artifact path", code="path_forbidden")

    safe_name = Path(filename).name
    if not safe_name or safe_name in {".", ".."}:
        raise HarnessError("invalid artifact filename", code="path_forbidden")

    if kind == "screenshot":
        base = Path(cfg.screenshot_storage)
    else:
        base = Path(cfg.artifact_storage)
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / base

    root = base.resolve()
    dest_dir = (root / job_id).resolve()
    if not _under_root(dest_dir, root) and dest_dir != root / job_id:
        if not str(dest_dir).startswith(str(root) + os.sep):
            raise HarnessError("job artifact path escape rejected", code="path_forbidden")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = (dest_dir / safe_name).resolve()
    if not _under_root(dest, dest_dir):
        raise HarnessError("artifact filename escape rejected", code="path_forbidden")
    return dest


def enforce_copy_size(path: Path, *, settings: Settings | None = None) -> int:
    cfg = settings or get_settings()
    size = path.stat().st_size
    if size > cfg.max_copy_bytes:
        raise HarnessError(
            f"copy exceeds MAX_COPY_BYTES ({cfg.max_copy_bytes})",
            code="copy_too_large",
        )
    return size


def guest_env_has_forbidden_keys(env_text: str) -> list[str]:
    found: list[str] = []
    for line in env_text.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else line.strip()
        if not key:
            continue
        if key in FORBIDDEN_ENV_KEYS:
            found.append(key)
            continue
        if key.endswith("_API_KEY") and key.startswith(("VULTR_", "OPENCODE_", "KILLHUB_")):
            found.append(key)
    return found
