"""Admission store unit tests — memory + fakeredis Valkey (D40 / D71)."""

from __future__ import annotations

import fakeredis
import pytest

from admission.errors import AdmissionRejected, AdmissionStoreError
from admission.factory import (
    get_admission_store,
    redact_url,
    reset_admission_store_for_tests,
)
from admission.memory import MemoryAdmissionStore
from admission.valkey import ValkeyAdmissionStore
from config import Settings, get_settings


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    reset_admission_store_for_tests()
    get_settings.cache_clear()
    yield
    reset_admission_store_for_tests()
    get_settings.cache_clear()


def test_memory_try_admit_and_release() -> None:
    store = MemoryAdmissionStore()
    store.try_admit(max_concurrent=1, max_queued=0)
    with pytest.raises(AdmissionRejected) as exc:
        store.try_admit(max_concurrent=1, max_queued=0)
    assert exc.value.code == "queue_full"
    assert exc.value.status_code == 503
    store.on_claimed()
    assert store.gauges() == {"running": 1, "queued": 0}
    store.on_terminal(was_running=True)
    assert store.gauges() == {"running": 0, "queued": 0}


def test_memory_rate_limit_per_ip() -> None:
    store = MemoryAdmissionStore()
    store.check_rate_limit("1.2.3.4", window_ms=60_000, per_ip_limit=2, global_limit=100)
    store.check_rate_limit("1.2.3.4", window_ms=60_000, per_ip_limit=2, global_limit=100)
    with pytest.raises(AdmissionRejected) as exc:
        store.check_rate_limit("1.2.3.4", window_ms=60_000, per_ip_limit=2, global_limit=100)
    assert exc.value.code == "rate_limited"
    assert exc.value.status_code == 429
    # Different IP still allowed.
    store.check_rate_limit("9.9.9.9", window_ms=60_000, per_ip_limit=2, global_limit=100)


def test_memory_rolling_inference() -> None:
    store = MemoryAdmissionStore()
    store.check_rolling_inference(tokens=50, budget=100, window_seconds=3600)
    store.record_inference_tokens(50, window_seconds=3600)
    store.check_rolling_inference(tokens=50, budget=100, window_seconds=3600)
    store.record_inference_tokens(50, window_seconds=3600)
    with pytest.raises(AdmissionRejected) as exc:
        store.check_rolling_inference(tokens=1, budget=100, window_seconds=3600)
    assert exc.value.code == "inference_budget"


def test_valkey_try_admit_rate_and_inference() -> None:
    fake = fakeredis.FakeRedis(decode_responses=True)
    store = ValkeyAdmissionStore(fake)
    store.ping()
    store.try_admit(max_concurrent=1, max_queued=1)
    store.try_admit(max_concurrent=1, max_queued=1)
    with pytest.raises(AdmissionRejected) as exc:
        store.try_admit(max_concurrent=1, max_queued=1)
    assert exc.value.code == "queue_full"
    store.on_claimed()
    assert store.gauges()["running"] == 1
    assert store.gauges()["queued"] == 1
    store.on_terminal(was_running=True)
    store.on_terminal(was_running=False)
    assert store.gauges() == {"running": 0, "queued": 0}

    store.check_rate_limit("10.0.0.1", window_ms=60_000, per_ip_limit=1, global_limit=10)
    with pytest.raises(AdmissionRejected):
        store.check_rate_limit("10.0.0.1", window_ms=60_000, per_ip_limit=1, global_limit=10)

    store.check_rolling_inference(tokens=10, budget=10, window_seconds=60)
    store.record_inference_tokens(10, window_seconds=60)
    with pytest.raises(AdmissionRejected):
        store.check_rolling_inference(tokens=1, budget=10, window_seconds=60)


def test_factory_memory_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMISSION_STORE", "memory")
    get_settings.cache_clear()
    reset_admission_store_for_tests()
    store = get_admission_store()
    assert store.backend == "memory"


def test_factory_valkey_requires_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMISSION_STORE", "valkey")
    monkeypatch.delenv("VALKEY_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    get_settings.cache_clear()
    reset_admission_store_for_tests()
    with pytest.raises(AdmissionStoreError):
        get_admission_store(Settings())


def test_redact_url_strips_password() -> None:
    redacted = redact_url("redis://user:s3cret@db.example:16724/0")
    assert "s3cret" not in redacted
    assert "db.example" in redacted
    assert "user@" in redacted


def test_valkey_reconcile() -> None:
    fake = fakeredis.FakeRedis(decode_responses=True)
    store = ValkeyAdmissionStore(fake)
    store.reconcile(running=3, queued=2)
    assert store.gauges() == {"running": 3, "queued": 2}
