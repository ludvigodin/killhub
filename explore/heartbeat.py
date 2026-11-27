"""Ledger heartbeats so jobs.updated_at reflects worker liveness (D81 / D50).

SSE comment keep-alives do not write the ledger. Long harness steps must bump
``updated_at`` so the reaper and UI can distinguish a live worker from a stall.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from config import Settings, get_settings
from jobs import get_ledger

logger = logging.getLogger("killhub.heartbeat")


def touch_job_heartbeat(
    job_id: str,
    *,
    settings: Settings | None = None,
    message: str = "worker heartbeat",
) -> None:
    """Append a progress heartbeat (bumps ``updated_at`` via the event path)."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    try:
        ledger.append_event(
            job_id,
            typ="progress",
            message=message,
            payload={"kind": "heartbeat"},
        )
    except Exception:  # noqa: BLE001 — never fail the pipeline on heartbeat
        logger.debug("heartbeat skipped for %s", job_id, exc_info=True)


class JobHeartbeat:
    """Background thread that heartbeats while a claimed job is running."""

    def __init__(
        self,
        job_id: str,
        *,
        settings: Settings | None = None,
        interval_seconds: float | None = None,
    ) -> None:
        cfg = settings or get_settings()
        self._job_id = job_id
        self._settings = cfg
        keep = float(getattr(cfg, "sse_keepalive_seconds", 15) or 15)
        self._interval = max(
            float(interval_seconds) if interval_seconds is not None else keep,
            5.0,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> JobHeartbeat:
        if self._thread is not None:
            return self
        touch_job_heartbeat(self._job_id, settings=self._settings)
        self._thread = threading.Thread(
            target=self._run,
            name=f"killhub-heartbeat-{self._job_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._interval + 1.0)
        self._thread = None

    def __enter__(self) -> JobHeartbeat:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            touch_job_heartbeat(self._job_id, settings=self._settings)


__all__ = ["JobHeartbeat", "touch_job_heartbeat"]
