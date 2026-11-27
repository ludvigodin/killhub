"""Vultr Container Registry helpers for host-side OCI pull (D74).

Plane 1 / VX1 host may authenticate to ``*.vultrcr.com`` to pull Killhub-owned
bootstrap and runtime base images. Robot credentials stay on the host — never
injected into guest sandbox env (D19, D44).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from config import Settings, get_settings
from errors import HarnessError

# ewr.vultrcr.com/killhub/bootstrap@sha256:…  or  ewr.vultrcr.com/killhub/bootstrap:tag
# Path segments stop before :tag / @digest so the optional suffix can match.
_VULTR_CR_REF = re.compile(
    r"(?i)^"
    r"(?:https?://)?"
    r"(?P<host>[a-z0-9-]+\.vultrcr\.com)"
    r"/(?P<path>(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+)"
    r"(?:"
    r"@(?P<digest>sha256:[a-f0-9]{64})"
    r"|"
    r":(?P<tag>[A-Za-z0-9_][A-Za-z0-9_.-]*)"
    r")?"
    r"$"
)

_DIGEST_SUFFIX = re.compile(r"(?i)@sha256:[a-f0-9]{64}$")

__all__ = [
    "OciImageRef",
    "is_vultr_cr_ref",
    "has_digest_pin",
    "parse_oci_image_ref",
    "validate_oci_image_ref",
    "require_host_registry_pull_ready",
]


@dataclass(frozen=True)
class OciImageRef:
    """Parsed OCI image reference (host path + optional tag/digest)."""

    raw: str
    host: str | None
    path: str
    tag: str | None
    digest: str | None
    is_vultr_cr: bool

    @property
    def repository(self) -> str:
        if self.host:
            return f"{self.host}/{self.path}"
        return self.path


def is_vultr_cr_ref(image: str) -> bool:
    """True when the ref points at a Vultr Container Registry host."""
    raw = (image or "").strip().lower()
    if not raw:
        return False
    raw = raw.removeprefix("https://").removeprefix("http://")
    return ".vultrcr.com/" in raw or raw.endswith(".vultrcr.com")


def has_digest_pin(image: str) -> bool:
    """True when the image is pinned with ``@sha256:<64 hex>``."""
    return bool(_DIGEST_SUFFIX.search((image or "").strip()))


def parse_oci_image_ref(image: str) -> OciImageRef:
    """Parse a bootstrap/runtime OCI image string (best-effort)."""
    raw = (image or "").strip()
    if not raw:
        raise HarnessError("oci image ref is empty", code="invalid_image")

    match = _VULTR_CR_REF.fullmatch(raw)
    if match:
        path = match.group("path").rstrip("/")
        if not path:
            raise HarnessError(
                f"invalid Vultr CR image ref (empty repository path): {raw}",
                code="invalid_image",
            )
        return OciImageRef(
            raw=raw,
            host=match.group("host").lower(),
            path=path,
            tag=match.group("tag"),
            digest=(match.group("digest") or None),
            is_vultr_cr=True,
        )

    # Non–Vultr-CR refs (public docker hub short names, ghcr, etc.)
    digest: str | None = None
    tag: str | None = None
    body = raw
    dig = _DIGEST_SUFFIX.search(body)
    if dig:
        digest = dig.group(0)[1:]  # drop leading @
        body = body[: dig.start()]
    elif ":" in body.rsplit("/", 1)[-1]:
        body, tag = body.rsplit(":", 1)

    host: str | None = None
    path = body
    if "/" in body and ("." in body.split("/", 1)[0] or body.startswith("localhost")):
        host, path = body.split("/", 1)

    return OciImageRef(
        raw=raw,
        host=host.lower() if host else None,
        path=path,
        tag=tag,
        digest=digest.lower() if digest else None,
        is_vultr_cr=False,
    )


def validate_oci_image_ref(image: str) -> OciImageRef:
    """Validate image ref shape; Vultr CR refs must include registry/repo path."""
    parsed = parse_oci_image_ref(image)
    if parsed.is_vultr_cr and not parsed.path:
        raise HarnessError(
            f"Vultr CR image must include registry/repository path: {image}",
            code="invalid_image",
        )
    if parsed.is_vultr_cr and parsed.digest is None and parsed.tag is None:
        # Bare ``ewr.vultrcr.com/killhub/bootstrap`` implies :latest — allowed for
        # local dx, but prod should pin by digest (D74).
        pass
    return parsed


def require_host_registry_pull_ready(
    image: str,
    settings: Settings | None = None,
) -> OciImageRef:
    """Fail-closed when a Vultr CR image is used without host robot credentials.

    Credentials are for the **host / msb pull path** only. Callers must never
    copy ``VULTR_CR_ROBOT_*`` into sandbox ``plan.env`` (D19, D44, D74).
    """
    cfg = settings or get_settings()
    parsed = validate_oci_image_ref(image)
    if not parsed.is_vultr_cr:
        return parsed

    require = bool(getattr(cfg, "vultr_cr_require_creds", True))
    if not require:
        return parsed

    user = (getattr(cfg, "vultr_cr_robot_username", None) or "").strip()
    password = (getattr(cfg, "vultr_cr_robot_password", None) or "").strip()
    if not user or not password:
        raise HarnessError(
            "Vultr Container Registry image requires host-side "
            "VULTR_CR_ROBOT_USERNAME and VULTR_CR_ROBOT_PASSWORD "
            "(Plane 1 / VX1 only — never inject into guest). "
            "Set VULTR_CR_REQUIRE_CREDS=false only for a deliberately public registry.",
            code="registry_creds_missing",
        )
    return parsed
