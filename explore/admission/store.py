"""Admission store protocol (memory or Valkey)."""

from __future__ import annotations

from typing import Protocol


class AdmissionStore(Protocol):
    """Shared admission counters / rate limits / rolling inference budgets."""

    backend: str

    def ping(self) -> None:
        """Fail closed when the backend is unreachable."""

    def try_admit(self, *, max_concurrent: int, max_queued: int) -> None:
        """Reserve a queue slot or raise AdmissionRejected (503 queue_full)."""

    def on_claimed(self) -> None:
        """Move one job from queued → running."""

    def on_terminal(self, *, was_running: bool) -> None:
        """Release a running or still-queued slot."""

    def check_rate_limit(
        self,
        ip: str,
        *,
        window_ms: int,
        per_ip_limit: int,
        global_limit: int,
    ) -> None:
        """Raise AdmissionRejected (429 rate_limited) when over limit."""

    def check_rolling_inference(
        self,
        *,
        tokens: int,
        budget: int,
        window_seconds: int,
    ) -> None:
        """Raise AdmissionRejected (429 inference_budget) when rolling budget exhausted."""

    def record_inference_tokens(self, tokens: int, *, window_seconds: int) -> None:
        """Add tokens toward the rolling window counter."""

    def gauges(self) -> dict[str, int]:
        """Non-secret admission gauges for health / ops."""
