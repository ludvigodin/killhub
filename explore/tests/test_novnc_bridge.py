"""Check the Plane 1 console's grant, lifecycle, and browser input boundaries."""

from __future__ import annotations

import asyncio
import io
import struct
from pathlib import Path

import pytest

from ledger import Ledger
from novnc_bridge import (
    RfbProtocolError,
    _active_generation,
    _client_message,
    _grant,
    _verify_grant,
)


def test_view_grant_is_bound_to_job_and_deadline() -> None:
    secret = "synthetic-view-signing-key-for-tests"
    grant = _grant(secret, "first-job", 2, 1200)

    assert _verify_grant(secret, "first-job", grant, 1100) == (2, 1200)
    assert _verify_grant(secret, "other-job", grant, 1100) is None
    assert _verify_grant(secret, "first-job", grant, 1200) is None
    assert _verify_grant(secret, "first-job", grant, 1000) is None
    assert _verify_grant(secret, "first-job", grant.replace("2.", "3.", 1), 1100) is None


def test_console_generation_stops_on_cancel_or_expiry(tmp_path: Path) -> None:
    with Ledger(tmp_path / "console.db") as ledger:
        job = ledger.create_job(
            "https://github.com/example/fixture", env_ttl_seconds=120, status="verifying"
        )
        generation = ledger.append_sandbox_generation(
            job.job_id,
            environment_id="trusted-console",
            image="ubuntu:24.04",
            expires_at=job.expires_at,
            state="running",
        )
        active = _active_generation(ledger, job.job_id, 0)
        assert active is not None and active[0] == generation.generation
        assert _active_generation(ledger, job.job_id, active[1]) is None

        # Even a valid unexpired grant cannot outlive the job's cancellation freeze.
        ledger.update_job_fields(job.job_id, cancel_requested_at=job.created_at)
        assert _active_generation(ledger, job.job_id, 0) is None


def _forwarded(payload: bytes) -> bytes | None:
    stream = io.BytesIO(payload)

    async def read(count: int) -> bytes:
        field = stream.read(count)
        assert len(field) == count
        return field

    result = asyncio.run(_client_message(read, 800, 600))
    assert stream.read() == b""
    return result


@pytest.mark.parametrize(
    "frame",
    [
        struct.pack(">BB2xI", 4, 1, ord("a")),
        struct.pack(">BBHH", 5, 1, 0, 0),
        struct.pack(">B3xI3s", 6, 3, b"abc"),
    ],
)
def test_console_input_is_consumed_without_forwarding(frame: bytes) -> None:
    assert _forwarded(frame) is None


def test_framebuffer_request_forwards_and_extensions_are_removed() -> None:
    request = struct.pack(">BBHHHH", 3, 1, 0, 0, 800, 600)
    offered = struct.pack(">BBH3i", 2, 0, 3, -223, 16, 0)

    assert _forwarded(request) == request
    assert _forwarded(offered) == struct.pack(">BBH2i", 2, 0, 2, 16, 0)


def test_unknown_message_and_invalid_framebuffer_fail_closed() -> None:
    with pytest.raises(RfbProtocolError, match="unsupported client message"):
        _forwarded(b"\xff")
    with pytest.raises(RfbProtocolError, match="invalid framebuffer request"):
        _forwarded(struct.pack(">BBHHHH", 3, 1, 0, 0, 801, 600))
