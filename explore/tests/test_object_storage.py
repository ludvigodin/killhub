"""Object storage backend selection + backup upload (D72) — no live Vultr bucket."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from object_storage import (
    SCREENSHOT_CDN_ACL,
    SCREENSHOT_CDN_CACHE_CONTROL,
    ObjectStorageError,
    cdn_url_for_key,
    cdn_url_for_s3_ref,
    filesystem_root_for_screenshots,
    is_s3_ref,
    make_s3_ref,
    maybe_upload_local_file,
    normalize_storage_backend,
    object_key,
    object_storage_origin_hostname,
    parse_s3_ref,
    prune_prefix,
    require_object_storage_config,
    reset_object_store_cache,
    resolve_storage_backend,
    upload_file,
)


class FakeObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.last_put: dict[str, object] | None = None

    def put_file(
        self,
        key: str,
        path: Path,
        *,
        content_type: str | None = None,
        acl: str | None = None,
        cache_control: str | None = None,
    ) -> None:
        self.last_put = {
            "key": key,
            "content_type": content_type,
            "acl": acl,
            "cache_control": cache_control,
        }
        self.objects[key] = path.read_bytes()

    def get_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def head_size(self, key: str) -> int | None:
        data = self.objects.get(key)
        return None if data is None else len(data)


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_object_store_cache()
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.delenv("SCREENSHOT_STORAGE", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_BUCKET", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_SECRET_KEY", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_PREFIX", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_CDN_BASE_URL", raising=False)
    monkeypatch.delenv("LEDGER_BACKUP_UPLOAD", raising=False)
    from config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    reset_object_store_cache()


def test_normalize_and_resolve_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert normalize_storage_backend("filesystem") == "filesystem"
    assert normalize_storage_backend("s3") == "s3"
    assert normalize_storage_backend("object") == "s3"
    with pytest.raises(ObjectStorageError):
        normalize_storage_backend("gcs")
    with pytest.raises(ObjectStorageError):
        normalize_storage_backend("./storage/screenshots")

    from config import get_settings

    assert resolve_storage_backend() == "filesystem"

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    get_settings.cache_clear()
    assert resolve_storage_backend() == "s3"

    monkeypatch.delenv("STORAGE_BACKEND")
    monkeypatch.setenv("SCREENSHOT_STORAGE", "object")
    get_settings.cache_clear()
    # Paths only — backend keywords on SCREENSHOT_STORAGE fail closed (use STORAGE_BACKEND).
    assert resolve_storage_backend() == "filesystem"
    with pytest.raises(ObjectStorageError, match="STORAGE_BACKEND"):
        filesystem_root_for_screenshots()

    monkeypatch.setenv("SCREENSHOT_STORAGE", str(tmp_path / "shots"))
    get_settings.cache_clear()
    assert resolve_storage_backend() == "filesystem"
    assert filesystem_root_for_screenshots() == (tmp_path / "shots").resolve()


def test_require_config_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    from config import get_settings

    get_settings.cache_clear()
    with pytest.raises(ObjectStorageError) as exc:
        require_object_storage_config()
    assert "OBJECT_STORAGE_ENDPOINT" in str(exc.value)
    assert "OBJECT_STORAGE_BUCKET" in str(exc.value)


def test_s3_ref_helpers() -> None:
    ref = make_s3_ref("killhub", "killhub/screenshots/j1/a.png")
    assert is_s3_ref(ref)
    assert parse_s3_ref(ref) == ("killhub", "killhub/screenshots/j1/a.png")
    assert object_key(kind="screenshot", job_id="j1", filename="a.png") == (
        "killhub/screenshots/j1/a.png"
    )
    assert object_key(kind="backup", filename="killhub-ledger-x.db") == (
        "killhub/backups/ledger/killhub-ledger-x.db"
    )


def _enable_object_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://ewr1.vultrobjects.com")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "killhub-test")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "AKIA_TEST")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "secret")
    monkeypatch.setenv("OBJECT_STORAGE_PREFIX", "killhub")
    from config import get_settings

    get_settings.cache_clear()


def test_maybe_upload_filesystem_keeps_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local = tmp_path / "shot.png"
    local.write_bytes(b"png")
    fake = FakeObjectStore()
    assert maybe_upload_local_file(
        local,
        kind="screenshot",
        job_id="job-1",
        client=fake,
    ) == str(local)
    assert fake.objects == {}


def test_maybe_upload_s3_returns_ref(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_object_env(monkeypatch)
    local = tmp_path / "shot.png"
    local.write_bytes(b"png-bytes")
    fake = FakeObjectStore()
    ref = maybe_upload_local_file(
        local,
        kind="screenshot",
        job_id="job-1",
        client=fake,
    )
    assert ref == "s3://killhub-test/killhub/screenshots/job-1/shot.png"
    assert fake.objects[parse_s3_ref(ref)[1]] == b"png-bytes"
    assert local.is_file()


def test_backup_upload_and_retention(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ledger.backup import backup_ledger
    from ledger.store import Ledger

    _enable_object_env(monkeypatch)
    db = tmp_path / "ledger.db"
    with Ledger(db) as ledger:
        ledger.create_job(
            "https://github.com/heroku/nodejs-getting-started",
            env_ttl_seconds=60,
        )
    dest = tmp_path / "backups"
    fake = FakeObjectStore()
    start = datetime(2026, 11, 20, tzinfo=timezone.utc)
    from datetime import timedelta

    for day in range(4):
        backup_ledger(
            db,
            dest,
            keep=2,
            now=start + timedelta(days=day),
            upload=True,
            object_client=fake,
        )
    local = sorted(p.name for p in dest.glob("killhub-ledger-*.db"))
    assert len(local) == 2
    remote = sorted(fake.objects)
    assert len(remote) == 2
    assert all(k.startswith("killhub/backups/ledger/") for k in remote)
    assert remote[-1].endswith(local[-1])


def test_prune_prefix_keeps_newest() -> None:
    fake = FakeObjectStore()
    for name in ("a.db", "b.db", "c.db"):
        fake.objects[f"killhub/backups/ledger/{name}"] = b"x"
    deleted = prune_prefix("killhub/backups/ledger/", keep=2, client=fake)
    assert deleted == ["killhub/backups/ledger/a.db"]
    assert sorted(fake.objects) == [
        "killhub/backups/ledger/b.db",
        "killhub/backups/ledger/c.db",
    ]


def test_upload_fail_closed_without_creds(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    from config import get_settings

    get_settings.cache_clear()
    local = tmp_path / "x.png"
    local.write_bytes(b"x")
    with pytest.raises(ObjectStorageError):
        upload_file(local, kind="screenshot", job_id="j", client=FakeObjectStore())


def test_cdn_url_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings

    assert cdn_url_for_key("killhub/screenshots/j/a.png") is None
    assert cdn_url_for_s3_ref("s3://b/killhub/screenshots/j/a.png") is None

    monkeypatch.setenv(
        "OBJECT_STORAGE_CDN_BASE_URL",
        "https://cdn-example.vultrcdn.com/",
    )
    get_settings.cache_clear()
    assert (
        cdn_url_for_key("killhub/screenshots/j/a.png")
        == "https://cdn-example.vultrcdn.com/killhub/screenshots/j/a.png"
    )
    assert (
        cdn_url_for_s3_ref("s3://killhub-test/killhub/screenshots/j/a.png")
        == "https://cdn-example.vultrcdn.com/killhub/screenshots/j/a.png"
    )
    assert cdn_url_for_s3_ref("./storage/screenshots/j/a.png") is None


def test_object_storage_origin_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import get_settings

    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT", "https://ewr1.vultrobjects.com")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "killhub-shots")
    get_settings.cache_clear()
    assert object_storage_origin_hostname() == "killhub-shots.ewr1.vultrobjects.com"
    assert (
        object_storage_origin_hostname(
            endpoint="https://killhub-shots.ewr1.vultrobjects.com",
            bucket="killhub-shots",
        )
        == "killhub-shots.ewr1.vultrobjects.com"
    )


def test_screenshot_upload_public_when_cdn_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_object_env(monkeypatch)
    monkeypatch.setenv(
        "OBJECT_STORAGE_CDN_BASE_URL",
        "https://cdn-example.vultrcdn.com",
    )
    from config import get_settings

    get_settings.cache_clear()
    local = tmp_path / "shot.png"
    local.write_bytes(b"png")
    fake = FakeObjectStore()
    ref = upload_file(
        local,
        kind="screenshot",
        job_id="job-1",
        content_type="image/png",
        client=fake,
    )
    assert ref.startswith("s3://")
    assert fake.last_put is not None
    assert fake.last_put["acl"] == SCREENSHOT_CDN_ACL
    assert fake.last_put["cache_control"] == SCREENSHOT_CDN_CACHE_CONTROL
    assert fake.last_put["content_type"] == "image/png"


def test_screenshot_upload_private_without_cdn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_object_env(monkeypatch)
    local = tmp_path / "shot.png"
    local.write_bytes(b"png")
    fake = FakeObjectStore()
    upload_file(local, kind="screenshot", job_id="job-1", client=fake)
    assert fake.last_put is not None
    assert fake.last_put["acl"] is None
    assert fake.last_put["cache_control"] is None


def test_artifact_upload_never_public_via_cdn_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_object_env(monkeypatch)
    monkeypatch.setenv(
        "OBJECT_STORAGE_CDN_BASE_URL",
        "https://cdn-example.vultrcdn.com",
    )
    from config import get_settings

    get_settings.cache_clear()
    local = tmp_path / "lock.txt"
    local.write_text("x")
    fake = FakeObjectStore()
    upload_file(local, kind="artifact", job_id="job-1", client=fake)
    assert fake.last_put is not None
    assert fake.last_put["acl"] is None
    assert fake.last_put["cache_control"] is None
