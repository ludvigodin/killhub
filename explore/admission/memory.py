"""In-process admission store — default for local/dev (D71)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from admission.errors import AdmissionRejected


class MemoryAdmissionStore:
    """Process-local counters; concurrency may also be ledger-validated by the caller."""

    backend = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = 0
        self._queued = 0
        self._ip_hits: dict[str, list[float]] = defaultdict(list)
        self._global_hits: list[float] = []
        self._inference: dict[int, int] = defaultdict(int)

    def ping(self) -> None:
        return None

    def try_admit(self, *, max_concurrent: int, max_queued: int) -> None:
        with self._lock:
            capacity = max_concurrent + max_queued
            active = self._running + self._queued
            if active >= capacity:
                raise AdmissionRejected(
                    "Job concurrency and queue are full",
                    code="queue_full",
                    status_code=503,
                )
            if self._running >= max_concurrent and self._queued >= max_queued:
                raise AdmissionRejected(
                    "Job concurrency and queue are full",
                    code="queue_full",
                    status_code=503,
                )
            self._queued += 1

    def on_claimed(self) -> None:
        with self._lock:
            if self._queued > 0:
                self._queued -= 1
            self._running += 1

    def on_terminal(self, *, was_running: bool) -> None:
        with self._lock:
            if was_running:
                if self._running > 0:
                    self._running -= 1
            elif self._queued > 0:
                self._queued -= 1

    def check_rate_limit(
        self,
        ip: str,
        *,
        window_ms: int,
        per_ip_limit: int,
        global_limit: int,
    ) -> None:
        now = time.monotonic()
        window_s = max(window_ms, 1) / 1000.0
        ip_key = ip or "unknown"
        with self._lock:
            ip_hits = [t for t in self._ip_hits[ip_key] if now - t < window_s]
            if per_ip_limit > 0 and len(ip_hits) >= per_ip_limit:
                self._ip_hits[ip_key] = ip_hits
                raise AdmissionRejected(
                    "Rate limit exceeded for job creation",
                    code="rate_limited",
                    status_code=429,
                )
            global_hits = [t for t in self._global_hits if now - t < window_s]
            if global_limit > 0 and len(global_hits) >= global_limit:
                self._global_hits = global_hits
                raise AdmissionRejected(
                    "Global job creation rate limit exceeded",
                    code="rate_limited",
                    status_code=429,
                )
            ip_hits.append(now)
            global_hits.append(now)
            self._ip_hits[ip_key] = ip_hits
            self._global_hits = global_hits

    def check_rolling_inference(
        self,
        *,
        tokens: int,
        budget: int,
        window_seconds: int,
    ) -> None:
        if budget <= 0 or window_seconds <= 0:
            return
        bucket = int(time.time()) // window_seconds
        with self._lock:
            used = self._inference.get(bucket, 0)
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
        with self._lock:
            self._inference[bucket] = self._inference.get(bucket, 0) + tokens
            # Drop stale buckets (keep current ±1).
            stale = [b for b in self._inference if abs(b - bucket) > 1]
            for b in stale:
                del self._inference[b]

    def gauges(self) -> dict[str, int]:
        with self._lock:
            return {
                "running": self._running,
                "queued": self._queued,
            }

    def reset_for_tests(self) -> None:
        with self._lock:
            self._running = 0
            self._queued = 0
            self._ip_hits.clear()
            self._global_hits.clear()
            self._inference.clear()
