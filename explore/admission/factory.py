"""Build the configured admission store (memory default, Valkey optional)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from admission.errors import AdmissionStoreError
from admission.memory import MemoryAdmissionStore
from admission.valkey import ValkeyAdmissionStore
from config import Settings, get_settings

logger = logging.getLogger("killhub.admission")

_STORE_ALIASES = {
    "memory": "memory",
    "local": "memory",
    "inmemory": "memory",
    "valkey": "valkey",
    "redis": "valkey",
}

_store: MemoryAdmissionStore | ValkeyAdmissionStore | None = None


def _normalize_backend(raw: str) -> str:
    key = (raw or "memory").strip().lower()
    if key not in _STORE_ALIASES:
        raise AdmissionStoreError(f"Unknown ADMISSION_STORE={raw!r}; use memory|valkey")
    return _STORE_ALIASES[key]


def resolve_valkey_url(settings: Settings) -> str:
    """VALKEY_URL preferred; REDIS_URL accepted as alias."""
    return (settings.valkey_url or settings.redis_url or "").strip()


def redact_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = f":{parsed.port}" if parsed.port else ""
    scheme = parsed.scheme or "redis"
    user = f"{parsed.username}@" if parsed.username else ""
    return f"{scheme}://{user}{host}{port}/"


def _connect_valkey(url: str) -> Any:
    try:
        import redis
    except ImportError as exc:  # pragma: no cover — declared in requirements
        raise AdmissionStoreError("redis package required for ADMISSION_STORE=valkey") from exc
    try:
        client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        if not client.ping():
            raise AdmissionStoreError("Valkey ping failed")
        return client
    except AdmissionStoreError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AdmissionStoreError(f"Valkey connect failed: {exc}") from exc


def get_admission_store(
    settings: Settings | None = None,
) -> MemoryAdmissionStore | ValkeyAdmissionStore:
    """Return the process admission store (singleton).

    ``settings`` is only used when the singleton is not yet built (first call
    after process start / ``reset_admission_store_for_tests``).
    """
    global _store
    if _store is not None:
        return _store
    cfg = settings or get_settings()
    backend = _normalize_backend(cfg.admission_store)
    if backend == "memory":
        _store = MemoryAdmissionStore()
        logger.info("admission store=memory")
        return _store

    url = resolve_valkey_url(cfg)
    if not url:
        raise AdmissionStoreError("ADMISSION_STORE=valkey requires VALKEY_URL or REDIS_URL")
    client = _connect_valkey(url)
    _store = ValkeyAdmissionStore(client, url_redacted=redact_url(url))
    logger.info("admission store=valkey url=%s", redact_url(url))
    return _store


def reset_admission_store_for_tests() -> None:
    global _store
    _store = None
