"""Activity-visible heartbeats for long-running Plane-2 waits."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar

from config import Settings
from jobs import get_ledger

T = TypeVar("T")


def log_progress(
    job_id: str,
    message: str,
    *,
    settings: Settings,
    kind: str = "heartbeat",
    **payload: Any,
) -> None:
    get_ledger(settings).append_event(
        job_id,
        typ="log",
        message=message,
        payload={"kind": kind, **payload},
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
    """Run ``fn`` while emitting Activity logs every ``interval_seconds``."""
    if announce:
        log_progress(job_id, f"{label}…", settings=settings)
    stop = threading.Event()
    started = time.monotonic()

    def pulse() -> None:
        while not stop.wait(interval_seconds):
            elapsed = int(time.monotonic() - started)
            log_progress(
                job_id,
                f"still {label} ({elapsed}s)",
                settings=settings,
                elapsed_seconds=elapsed,
            )

    thread = threading.Thread(
        target=pulse,
        name=f"kh-hb-{label[:24].replace(' ', '-')}",
        daemon=True,
    )
    thread.start()
    try:
        return fn()
    finally:
        stop.set()
        thread.join(timeout=1.0)
