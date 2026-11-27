"""Vultr Object Storage (S3-compatible) helpers for Plane 1 only (D72).

Credentials never leave the control plane — do not inject into sandboxes (D19, D44).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from config import Settings, get_settings

logger = logging.getLogger("killhub.object_storage")

S3_SCHEME = "s3://"
BACKEND_FILESYSTEM = "filesystem"
BACKEND_S3 = "s3"
BACKEND_ALIASES = frozenset({"s3", "object", "object_storage", "vultr"})


class ObjectStorageError(RuntimeError):
    """Misconfiguration or S3 operation failure (fail closed for object mode)."""


class ObjectStoreClient(Protocol):
    def put_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str | None = None,
        acl: str | None = None,
        cache_control: str | None = None,
    ) -> None: ...

    def get_bytes(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def list_keys(self, prefix: str) -> list[str]: ...

    def head_size(self, key: str) -> int | None: ...


# Screenshot stills served via CDN Pull Zone (D76).
SCREENSHOT_CDN_CACHE_CONTROL = "public, max-age=86400"
SCREENSHOT_CDN_ACL = "public-read"


@dataclass(frozen=True)
class ObjectStorageConfig:
    endpoint: str
    region: str
    bucket: str
    access_key: str
    secret_key: str
    prefix: str

    @property
    def endpoint_url(self) -> str:
        raw = self.endpoint.strip()
        if not raw:
            return ""
        if raw.startswith("http://") or raw.startswith("https://"):
            return raw.rstrip("/")
        return f"https://{raw.rstrip('/')}"


def normalize_storage_backend(raw: str | None) -> str:
    value = (raw or BACKEND_FILESYSTEM).strip().lower()
    if value in BACKEND_ALIASES:
        return BACKEND_S3
    if value in {"", BACKEND_FILESYSTEM, "fs", "local"}:
        return BACKEND_FILESYSTEM
    raise ObjectStorageError(
        f"unknown storage backend {raw!r}; use filesystem or s3/object",
    )


def resolve_storage_backend(settings: Settings | None = None) -> str:
    """Pick filesystem (default) vs s3/object from STORAGE_BACKEND (D72)."""
    cfg = settings or get_settings()
    explicit = (cfg.storage_backend or "").strip()
    if explicit:
        return normalize_storage_backend(explicit)
    return BACKEND_FILESYSTEM


def _local_storage_root(raw: str, *, default: str, env_name: str) -> Path:
    """Resolve a local staging path; reject backend keywords that belong on STORAGE_BACKEND."""
    value = (raw or "").strip()
    if not value:
        value = default
    elif value.lower() in BACKEND_ALIASES:
        raise ObjectStorageError(
            f"{env_name}={value!r} is a path; set STORAGE_BACKEND=s3|object for object storage",
        )
    base = Path(value)
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / base
    return base.resolve()


def filesystem_root_for_screenshots(settings: Settings | None = None) -> Path:
    """Local staging / filesystem root for screenshots (D17, D60)."""
    cfg = settings or get_settings()
    return _local_storage_root(
        cfg.screenshot_storage,
        default="./storage/screenshots",
        env_name="SCREENSHOT_STORAGE",
    )


def filesystem_root_for_artifacts(settings: Settings | None = None) -> Path:
    cfg = settings or get_settings()
    return _local_storage_root(
        cfg.artifact_storage,
        default="./storage/artifacts",
        env_name="ARTIFACT_STORAGE",
    )


def object_storage_config(settings: Settings | None = None) -> ObjectStorageConfig:
    cfg = settings or get_settings()
    return ObjectStorageConfig(
        endpoint=(cfg.object_storage_endpoint or "").strip(),
        region=(cfg.object_storage_region or "us-east-1").strip() or "us-east-1",
        bucket=(cfg.object_storage_bucket or "").strip(),
        access_key=(cfg.object_storage_access_key or "").strip(),
        secret_key=(cfg.object_storage_secret_key or "").strip(),
        prefix=(cfg.object_storage_prefix or "killhub").strip().strip("/") or "killhub",
    )


def require_object_storage_config(settings: Settings | None = None) -> ObjectStorageConfig:
    conf = object_storage_config(settings)
    missing = [
        name
        for name, val in (
            ("OBJECT_STORAGE_ENDPOINT", conf.endpoint),
            ("OBJECT_STORAGE_BUCKET", conf.bucket),
            ("OBJECT_STORAGE_ACCESS_KEY", conf.access_key),
            ("OBJECT_STORAGE_SECRET_KEY", conf.secret_key),
        )
        if not val
    ]
    if missing:
        raise ObjectStorageError(
            "object storage backend requires "
            + ", ".join(missing)
            + " (Plane 1 only — never inject into sandboxes)",
        )
    return conf


def is_s3_ref(value: str | None) -> bool:
    return bool(value) and str(value).startswith(S3_SCHEME)


def parse_s3_ref(ref: str) -> tuple[str, str]:
    """Return (bucket, key) from s3://bucket/key."""
    if not is_s3_ref(ref):
        raise ObjectStorageError(f"not an s3 ref: {ref!r}")
    parsed = urlparse(ref)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    if not bucket or not key:
        raise ObjectStorageError(f"invalid s3 ref: {ref!r}")
    return bucket, key


def make_s3_ref(bucket: str, key: str) -> str:
    return f"{S3_SCHEME}{bucket}/{key.lstrip('/')}"


def object_key(
    *,
    kind: str,
    job_id: str | None = None,
    filename: str,
    prefix: str = "killhub",
) -> str:
    """Stable object key under the Killhub prefix."""
    safe_kind = kind.strip().lower().rstrip("s")
    folder = {
        "screenshot": "screenshots",
        "artifact": "artifacts",
        "lockfile": "artifacts",
        "log": "artifacts",
        "backup": "backups/ledger",
    }.get(safe_kind, "artifacts")
    name = Path(filename).name
    if folder == "backups/ledger":
        return f"{prefix}/{folder}/{name}"
    if not job_id:
        raise ObjectStorageError("job_id required for artifact object keys")
    return f"{prefix}/{folder}/{job_id}/{name}"


class Boto3ObjectStore:
    """Thin boto3 wrapper for Vultr Object Storage."""

    def __init__(self, conf: ObjectStorageConfig, *, client: Any | None = None) -> None:
        self.conf = conf
        if client is not None:
            self._client = client
            return
        try:
            import boto3
            from botocore.client import Config as BotoConfig
        except ImportError as exc:  # pragma: no cover - dep declared in requirements
            raise ObjectStorageError(
                "boto3 is required for object storage; install explore requirements",
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=conf.endpoint_url,
            region_name=conf.region,
            aws_access_key_id=conf.access_key,
            aws_secret_access_key=conf.secret_key,
            config=BotoConfig(signature_version="s3v4"),
        )

    def put_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str | None = None,
        acl: str | None = None,
        cache_control: str | None = None,
    ) -> None:
        extra: dict[str, Any] = {}
        if content_type:
            extra["ContentType"] = content_type
        if acl:
            extra["ACL"] = acl
        if cache_control:
            extra["CacheControl"] = cache_control
        kwargs: dict[str, Any] = {}
        if extra:
            kwargs["ExtraArgs"] = extra
        self._client.upload_file(str(path), self.conf.bucket, key, **kwargs)

    def get_bytes(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self.conf.bucket, Key=key)
        body = resp["Body"].read()
        return bytes(body)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.conf.bucket, Key=key)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": self.conf.bucket,
                "Prefix": prefix,
            }
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            for item in resp.get("Contents") or []:
                key = item.get("Key")
                if key:
                    keys.append(str(key))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
            if not token:
                break
        return keys

    def head_size(self, key: str) -> int | None:
        try:
            resp = self._client.head_object(Bucket=self.conf.bucket, Key=key)
        except Exception:  # noqa: BLE001 — missing key / network → treat as absent
            return None
        size = resp.get("ContentLength")
        return int(size) if size is not None else None


_client_cache: ObjectStoreClient | None = None
_client_cache_key: tuple[str, ...] | None = None


def get_object_store(
    settings: Settings | None = None,
    *,
    client: ObjectStoreClient | None = None,
) -> ObjectStoreClient:
    """Return a configured store; fail closed when object backend lacks credentials."""
    if client is not None:
        return client
    global _client_cache, _client_cache_key
    conf = require_object_storage_config(settings)
    cache_key = (
        conf.endpoint_url,
        conf.region,
        conf.bucket,
        conf.access_key,
        conf.prefix,
    )
    if _client_cache is not None and _client_cache_key == cache_key:
        return _client_cache
    store = Boto3ObjectStore(conf)
    _client_cache = store
    _client_cache_key = cache_key
    return store


def reset_object_store_cache() -> None:
    global _client_cache, _client_cache_key
    _client_cache = None
    _client_cache_key = None


def cdn_base_url(settings: Settings | None = None) -> str:
    """Normalized CDN Pull Zone base (no trailing slash), or empty when unset (D76)."""
    cfg = settings or get_settings()
    return (cfg.object_storage_cdn_base_url or "").strip().rstrip("/")


def object_storage_origin_hostname(
    *,
    endpoint: str | None = None,
    bucket: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Virtual-host origin host for a Vultr CDN Pull Zone (D76).

    Form: ``{bucket}.{cluster}.vultrobjects.com`` — not the path-style API endpoint.
    """
    conf = object_storage_config(settings)
    ep = (endpoint if endpoint is not None else conf.endpoint).strip()
    bkt = (bucket if bucket is not None else conf.bucket).strip()
    if not ep or not bkt:
        raise ObjectStorageError(
            "OBJECT_STORAGE_ENDPOINT and OBJECT_STORAGE_BUCKET required for CDN origin",
        )
    raw = ep
    if raw.startswith("http://") or raw.startswith("https://"):
        host = urlparse(raw).hostname or ""
    else:
        host = raw.split("/")[0]
    host = host.strip().rstrip(".")
    if not host:
        raise ObjectStorageError(f"cannot parse object storage host from {ep!r}")
    # Already virtual-host style (bucket.cluster.vultrobjects.com).
    if host.startswith(f"{bkt}."):
        return host
    return f"{bkt}.{host}"


def cdn_url_for_key(key: str, *, settings: Settings | None = None) -> str | None:
    """Absolute CDN URL for an object key, or None when CDN is not configured."""
    base = cdn_base_url(settings)
    if not base or not key:
        return None
    return f"{base}/{key.lstrip('/')}"


def cdn_url_for_s3_ref(
    storage_ref: str,
    *,
    settings: Settings | None = None,
) -> str | None:
    """CDN URL for an s3:// ref, or None when not an s3 ref / CDN unset."""
    if not is_s3_ref(storage_ref):
        return None
    _bucket, key = parse_s3_ref(storage_ref)
    return cdn_url_for_key(key, settings=settings)


def _public_screenshot_upload(
    kind: str,
    *,
    settings: Settings | None = None,
) -> bool:
    """True when screenshot uploads should be public-read for CDN (D76)."""
    return kind == "screenshot" and bool(cdn_base_url(settings))


def upload_file(
    path: Path,
    *,
    kind: str,
    job_id: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    settings: Settings | None = None,
    client: ObjectStoreClient | None = None,
) -> str:
    """Upload a local file; return s3://bucket/key ref."""
    cfg = settings or get_settings()
    conf = require_object_storage_config(cfg)
    store = get_object_store(cfg, client=client)
    name = filename or path.name
    key = object_key(
        kind=kind,
        job_id=job_id,
        filename=name,
        prefix=conf.prefix,
    )
    acl: str | None = None
    cache_control: str | None = None
    if _public_screenshot_upload(kind, settings=cfg):
        acl = SCREENSHOT_CDN_ACL
        cache_control = SCREENSHOT_CDN_CACHE_CONTROL
    store.put_file(
        key,
        path,
        content_type=content_type,
        acl=acl,
        cache_control=cache_control,
    )
    ref = make_s3_ref(conf.bucket, key)
    logger.info("uploaded %s → %s", path.name, ref)
    return ref


def read_bytes(
    storage_ref: str,
    *,
    settings: Settings | None = None,
    client: ObjectStoreClient | None = None,
) -> bytes:
    if is_s3_ref(storage_ref):
        bucket, key = parse_s3_ref(storage_ref)
        conf = require_object_storage_config(settings)
        if bucket != conf.bucket:
            raise ObjectStorageError(
                f"s3 ref bucket {bucket!r} does not match OBJECT_STORAGE_BUCKET",
            )
        return get_object_store(settings, client=client).get_bytes(key)
    path = Path(storage_ref)
    if not path.is_file():
        raise FileNotFoundError(storage_ref)
    return path.read_bytes()


def maybe_upload_local_file(
    path: Path,
    *,
    kind: str,
    job_id: str | None = None,
    filename: str | None = None,
    content_type: str | None = None,
    settings: Settings | None = None,
    client: ObjectStoreClient | None = None,
) -> str:
    """
    When object backend is enabled, upload and return s3:// ref; else return local path.

    Local file is left in place as a hot cache (D60 staging still applies).
    """
    cfg = settings or get_settings()
    if resolve_storage_backend(cfg) != BACKEND_S3:
        return str(path)
    return upload_file(
        path,
        kind=kind,
        job_id=job_id,
        filename=filename,
        content_type=content_type,
        settings=cfg,
        client=client,
    )


def prune_prefix(
    prefix: str,
    *,
    keep: int,
    settings: Settings | None = None,
    client: ObjectStoreClient | None = None,
) -> list[str]:
    """Delete oldest keys under prefix until ``keep`` remain. Returns deleted keys."""
    if keep < 1:
        raise ValueError("keep must be at least 1")
    store = get_object_store(settings, client=client)
    keys = sorted(store.list_keys(prefix))
    deleted: list[str] = []
    for old in keys[:-keep]:
        store.delete(old)
        deleted.append(old)
    return deleted
