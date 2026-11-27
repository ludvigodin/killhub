"""Ledger heartbeats so jobs.updated_at reflects worker liveness (D83 / D50).

SSE comment keep-alives do not write the ledger. Long harness steps must bump
``updated_at`` so the reaper and UI can distinguish a live worker from a stall.

Labeled :func:`with_heartbeat` wraps emit Activity-visible ``log`` events for
long Plane-2 waits (msb create, clone, apt, snapshot).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, TypeVar

from config import Settings, get_settings
from jobs import get_ledger

logger = logging.getLogger("killhub.heartbeat")

T = TypeVar("T")


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


def log_wait(
    job_id: str,
    message: str,
    *,
    settings: Settings,
    kind: str = "wait",
    update_step: bool = True,
    **payload: Any,
) -> None:
    """Activity-visible log for a long-running step (not the D83 liveness pulse).

    When ``update_step`` is true, also mirrors ``message`` onto the job's
    ``current_step`` so the live progress line tracks the wait.
    """
    ledger = get_ledger(settings)
    body: dict[str, Any] = {"kind": kind, **payload}
    if update_step:
        body.setdefault("current_step", message)
        try:
            ledger.update_job_fields(job_id, current_step=message)
        except Exception:  # noqa: BLE001 — never fail the pipeline on UI pulse
            logger.debug("current_step update skipped for %s", job_id, exc_info=True)
    ledger.append_event(
        job_id,
        typ="log",
        message=message,
        payload=body,
    )


def with_heartbeat(
    job_id: str,
    *,
    settings: Settings,
    label: str,
    fn: Callable[[], T],
    interval_seconds: float = 15.0,
    announce: bool = True,
) -> T:
    """Run ``fn`` while emitting Activity logs every ``interval_seconds``.

    Each pulse updates ``current_step`` so the Progress line stays live during
    long msb/clone/apt waits.
    """
    if announce:
        log_wait(job_id, f"{label}…", settings=settings)
    stop = threading.Event()
    started = time.monotonic()

    def pulse() -> None:
        while not stop.wait(interval_seconds):
            elapsed = int(time.monotonic() - started)
            log_wait(
                job_id,
                f"still {label} ({elapsed}s)",
                settings=settings,
                elapsed_seconds=elapsed,
            )

    thread = threading.Thread(
        target=pulse,
        name=f"kh-wait-{label[:24].replace(' ', '-')}",
        daemon=True,
    )
    thread.start()
    try:
        return fn()
    finally:
        stop.set()
        thread.join(timeout=1.0)


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


__all__ = [
    "JobHeartbeat",
    "log_wait",
    "touch_job_heartbeat",
    "with_heartbeat",
]
