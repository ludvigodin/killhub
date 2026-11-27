"""Shared Valkey key layout for Plane 1 admission (no secrets in values)."""

from __future__ import annotations

PREFIX = "killhub:adm:v1"


def running_key() -> str:
    return f"{PREFIX}:running"


def queued_key() -> str:
    return f"{PREFIX}:queued"


def rate_ip_key(ip: str, bucket: int) -> str:
    # IP is opaque coordination data — never store auth tokens here.
    safe = ip.replace(" ", "_")[:128] or "unknown"
    return f"{PREFIX}:rl:ip:{safe}:{bucket}"


def rate_global_key(bucket: int) -> str:
    return f"{PREFIX}:rl:global:{bucket}"


def inference_rolling_key(bucket: int) -> str:
    return f"{PREFIX}:inf:{bucket}"
