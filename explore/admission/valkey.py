"""Vultr Managed Valkey (Redis-compatible) admission store (D71)."""

from __future__ import annotations

import logging
import time
from typing import Any

from admission import keys
from admission.errors import AdmissionRejected, AdmissionStoreError

logger = logging.getLogger("killhub.admission")


class ValkeyAdmissionStore:
    """Shared admission state on Redis-compatible Valkey. Plane 1 only."""

    backend = "valkey"

    def __init__(self, client: Any, *, url_redacted: str = "valkey") -> None:
        self._r = client
        self._url_redacted = url_redacted

    def ping(self) -> None:
        try:
            if not self._r.ping():
                raise AdmissionStoreError("Valkey ping failed")
        except AdmissionStoreError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as store error
            logger.error("admission Valkey unreachable: %s", exc)
            raise AdmissionStoreError(f"Valkey unavailable: {exc}") from exc

    def try_admit(self, *, max_concurrent: int, max_queued: int) -> None:
        """Atomically reserve a queue slot (WATCH/MULTI — works with fakeredis)."""
        self.ping()
        running_k = keys.running_key()
        queued_k = keys.queued_key()
        try:
            import redis as redis_mod

            watch_error = redis_mod.WatchError
        except Exception:  # noqa: BLE001
            watch_error = Exception  # type: ignore[assignment,misc]

        try:
            with self._r.pipeline() as pipe:
                while True:
                    try:
                        pipe.watch(running_k, queued_k)
                        running = int(pipe.get(running_k) or 0)
                        queued = int(pipe.get(queued_k) or 0)
                        capacity = max_concurrent + max_queued
                        if running + queued >= capacity:
                            pipe.unwatch()
                            raise AdmissionRejected(
                                "Job concurrency and queue are full",
                                code="queue_full",
                                status_code=503,
                            )
                        if running >= max_concurrent and queued >= max_queued:
                            pipe.unwatch()
                            raise AdmissionRejected(
                                "Job concurrency and queue are full",
                                code="queue_full",
                                status_code=503,
                            )
                        pipe.multi()
                        pipe.incr(queued_k)
                        pipe.execute()
                        return
                    except watch_error:
                        continue
        except AdmissionRejected:
            raise
        except AdmissionStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("admission try_admit failed: %s", exc)
            raise AdmissionStoreError(f"Valkey admit failed: {exc}") from exc

    def on_claimed(self) -> None:
        queued_k = keys.queued_key()
        running_k = keys.running_key()
        try:
            queued = int(self._r.get(queued_k) or 0)
            pipe = self._r.pipeline()
            if queued > 0:
                pipe.decr(queued_k)
            pipe.incr(running_k)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001 — best-effort; log drift
            logger.error("admission on_claimed failed: %s", exc)

    def on_terminal(self, *, was_running: bool) -> None:
        try:
            if was_running:
                key = keys.running_key()
            else:
                key = keys.queued_key()
            val = int(self._r.get(key) or 0)
            if val > 0:
                self._r.decr(key)
        except Exception as exc:  # noqa: BLE001
            logger.error("admission on_terminal failed: %s", exc)

    def check_rate_limit(
        self,
        ip: str,
        *,
        window_ms: int,
        per_ip_limit: int,
        global_limit: int,
    ) -> None:
        self.ping()
        window_ms = max(int(window_ms), 1)
        ttl_ms = window_ms * 2
        bucket = int(time.time() * 1000) // window_ms
        try:
            if per_ip_limit > 0:
                ip_key = keys.rate_ip_key(ip or "unknown", bucket)
                ip_n = int(self._r.incr(ip_key))
                if ip_n == 1:
                    self._r.pexpire(ip_key, ttl_ms)
                if ip_n > per_ip_limit:
                    raise AdmissionRejected(
                        "Rate limit exceeded for job creation",
                        code="rate_limited",
                        status_code=429,
                    )
            if global_limit > 0:
                g_key = keys.rate_global_key(bucket)
                g_n = int(self._r.incr(g_key))
                if g_n == 1:
                    self._r.pexpire(g_key, ttl_ms)
                if g_n > global_limit:
                    raise AdmissionRejected(
                        "Global job creation rate limit exceeded",
                        code="rate_limited",
                        status_code=429,
                    )
        except AdmissionRejected:
            raise
        except AdmissionStoreError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("admission rate limit failed: %s", exc)
            raise AdmissionStoreError(f"Valkey rate limit failed: {exc}") from exc

    def check_rolling_inference(
        self,
        *,
        tokens: int,
        budget: int,
        window_seconds: int,
    ) -> None:
        if budget <= 0 or window_seconds <= 0:
            return
        self.ping()
        bucket = int(time.time()) // window_seconds
        key = keys.inference_rolling_key(bucket)
        try:
            used = int(self._r.get(key) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.error("admission rolling inference read failed: %s", exc)
            raise AdmissionStoreError(f"Valkey inference read failed: {exc}") from exc
        if used + max(tokens, 0) > budget:
            raise AdmissionRejected(
                "Rolling inference budget exhausted",
                code="inference_budget",
                status_code=429,
            )

    def record_inference_tokens(self, tokens: int, *, window_seconds: int) -> None:
        if tokens <= 0 or window_seconds <= 0:
            return
        bucket = int(time.time()) // window_seconds
        key = keys.inference_rolling_key(bucket)
        try:
            pipe = self._r.pipeline()
            pipe.incrby(key, int(tokens))
            pipe.expire(key, window_seconds * 2)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.error("admission record_inference_tokens failed: %s", exc)

    def gauges(self) -> dict[str, int]:
        try:
            running = int(self._r.get(keys.running_key()) or 0)
            queued = int(self._r.get(keys.queued_key()) or 0)
            return {"running": running, "queued": queued}
        except Exception:  # noqa: BLE001
            return {"running": -1, "queued": -1}

    def reconcile(self, *, running: int, queued: int) -> None:
        """Overwrite counters from ledger snapshot (startup / ops)."""
        try:
            pipe = self._r.pipeline()
            pipe.set(keys.running_key(), max(0, int(running)))
            pipe.set(keys.queued_key(), max(0, int(queued)))
            pipe.execute()
            logger.info(
                "admission Valkey reconciled running=%s queued=%s",
                running,
                queued,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("admission reconcile failed: %s", exc)
            raise AdmissionStoreError(f"Valkey reconcile failed: {exc}") from exc
