"""Plane 1 view-only RFB bridge for trusted, operator-provisioned guest displays.

Only a server-owned Unix socket for the active job and generation is reachable.
The public WebSocket accepts short-lived grants from the private operator API.
"""

from __future__ import annotations

import asyncio
import hmac
import os
import re
import stat
import struct
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from time import time
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from config import Settings, get_settings
from jobs import get_ledger
from ledger import Ledger

GRANT_LIFETIME = 120
_IO_TIMEOUT = 5
_LIFECYCLE_INTERVAL = 0.25
_MAX_WS_MESSAGE = 65536
_MAX_DESKTOP_SIZE = 4096
_VERSION = b"RFB 003.008\n"
_SECURITY_NONE = b"\x01"
_GRANT_PREFIX = "killhub-view."
_GRANT_FORMAT = re.compile(r"([1-9][0-9]{0,9})\.([0-9]{1,12})\.([0-9a-f]{64})")
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
# Only ordinary framebuffer encodings. No desktop resize, clipboard, or input extensions.
_ENCODINGS = frozenset({0, 1, 2, 5, 16})
_PIXEL_FORMAT = struct.pack(">3xBBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 0, 8, 16)
router = APIRouter()


class RfbProtocolError(ValueError):
    """The connection cannot continue safely after a malformed or unsupported message."""


def _valid_job_id(job_id: str) -> bool:
    try:
        return str(UUID(job_id)) == job_id
    except ValueError:
        return False


def _enabled(settings: Settings) -> bool:
    if not settings.novnc_enabled or not Path(settings.novnc_socket_root).is_absolute():
        return False
    try:
        origin = urlsplit(settings.novnc_allowed_origin)
        port = origin.port
    except ValueError:
        return False
    secrets = (
        settings.novnc_token_secret.get_secret_value(),
        settings.novnc_operator_token.get_secret_value(),
    )
    return (
        origin.scheme == "https"
        and bool(origin.hostname)
        and (port is None or port > 0)
        and settings.novnc_allowed_origin == f"https://{origin.netloc}"
        and origin.username is None
        and all(len(key.encode()) >= 32 for key in secrets)
        and len(set(secrets)) == 2
        and settings.internal_api_token not in secrets
    )


def _signature(secret: str, job_id: str, generation: int, expires_at: int) -> str:
    grant = f"killhub:view-only:{job_id}:{generation}:{expires_at}".encode()
    return hmac.digest(secret.encode(), grant, "sha256").hex()


def _grant(secret: str, job_id: str, generation: int, expires_at: int) -> str:
    return f"{generation}.{expires_at}.{_signature(secret, job_id, generation, expires_at)}"


def _verify_grant(secret: str, job_id: str, token: str, now: float) -> tuple[int, int] | None:
    match = _GRANT_FORMAT.fullmatch(token)
    if not match:
        return None
    generation, expires_at = int(match[1]), int(match[2])
    if not now < expires_at <= now + GRANT_LIFETIME:
        return None
    if not hmac.compare_digest(_signature(secret, job_id, generation, expires_at), match[3]):
        return None
    return generation, expires_at


def _expires_at(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.timestamp()
    except (ValueError, OverflowError):
        pass
    return 0


def _active_generation(ledger: Ledger, job_id: str, now: float) -> tuple[int, float] | None:
    job = ledger.get_job(job_id)
    if (
        job is None
        or job.status in _TERMINAL
        or job.cancel_requested_at is not None
        or job.cleanup.status != "pending"
        or job.current_sandbox_generation is None
        or not job.sandbox_id
    ):
        return None
    deadline = _expires_at(job.expires_at)
    if deadline <= now:
        return None
    for gen in ledger.list_sandbox_generations(job_id):
        if gen.generation == job.current_sandbox_generation:
            deadline = min(deadline, _expires_at(gen.expires_at))
            if gen.environment_id == job.sandbox_id and gen.state == "running" and now < deadline:
                return gen.generation, deadline
            break
    return None


def _trusted_socket(root: Path, job_id: str, generation: int) -> Path:
    path = root / f"{job_id}.{generation}.sock"
    if not root.is_absolute() or ".." in root.parts or len(os.fsencode(path)) > 107:
        raise ValueError("invalid console socket path")
    trusted_owners = {0, os.geteuid()}
    # Reject symlinks and writable ancestors to keep the connect inside the operator's root.
    for parent in path.parents:
        info = parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in trusted_owners
            or info.st_mode & 0o022
        ):
            raise ValueError("insecure console socket directory")
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid not in trusted_owners or info.st_mode & 0o022:
        raise ValueError("insecure console socket")
    return path


class _BrowserInput:
    """RFB fields can span browser frames or share one frame."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.buffer = bytearray()

    async def read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            event = await self.websocket.receive()
            if event["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(event.get("code", 1000))
            chunk = event.get("bytes")
            if not chunk or len(chunk) > _MAX_WS_MESSAGE:
                raise RfbProtocolError("expected bounded binary message")
            self.buffer.extend(chunk)
        field = bytes(self.buffer[:count])
        del self.buffer[:count]
        return field


async def _client_message(
    read: Callable[[int], Awaitable[bytes]], width: int, height: int
) -> bytes | None:
    kind = await read(1)
    if kind == b"\x00":
        body = await read(19)
        if body != _PIXEL_FORMAT:
            raise RfbProtocolError("unsupported pixel format")
        return kind + body
    if kind == b"\x02":
        _, count = struct.unpack(">BH", await read(3))
        if count > 64:
            raise RfbProtocolError("too many encoding identifiers")
        offered = struct.unpack(f">{count}i", await read(count * 4))
        allowed = tuple(dict.fromkeys(item for item in offered if item in _ENCODINGS)) or (0,)
        return struct.pack(f">BBH{len(allowed)}i", 2, 0, len(allowed), *allowed)
    if kind == b"\x03":
        body = await read(9)
        incremental, x, y, w, h = struct.unpack(">BHHHH", body)
        if incremental > 1 or not w or not h or x + w > width or y + h > height:
            raise RfbProtocolError("invalid framebuffer request")
        return kind + body
    # Consume the complete standard input message, then discard it.
    if kind == b"\x04":
        if (await read(7))[0] > 1:
            raise RfbProtocolError("invalid key event")
        return None
    if kind == b"\x05":
        await read(5)
        return None
    if kind == b"\x06":
        length = int.from_bytes((await read(7))[3:], "big")
        if length > _MAX_WS_MESSAGE:
            raise RfbProtocolError("unsupported clipboard message")
        await read(length)
        return None
    raise RfbProtocolError("unsupported client message")


async def _handshake(
    websocket: WebSocket,
    browser: _BrowserInput,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> tuple[int, int]:
    # The private transport substitutes for RFB-level auth. Require RFB 3.8 with no extensions.
    for server, client in (
        (_VERSION, _VERSION),
        (b"\x01" + _SECURITY_NONE, _SECURITY_NONE),
        (b"\x00" * 4, b"\x01"),
    ):
        if await reader.readexactly(len(server)) != server:
            raise RfbProtocolError("unsupported server handshake")
        await websocket.send_bytes(server)
        if await browser.read(len(client)) != client:
            raise RfbProtocolError("unsupported client handshake")
        writer.write(client)
        await writer.drain()
    header = await reader.readexactly(24)
    width, height = struct.unpack(">HH", header[:4])
    name_length = int.from_bytes(header[20:], "big")
    if (
        not (0 < width <= _MAX_DESKTOP_SIZE and 0 < height <= _MAX_DESKTOP_SIZE)
        or name_length > 256
    ):
        raise RfbProtocolError("unsupported framebuffer geometry")
    await websocket.send_bytes(header + await reader.readexactly(name_length))
    return width, height


async def _relay(
    websocket: WebSocket,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    ledger: Ledger,
    job_id: str,
    generation: int,
    expires_at: int,
) -> int:
    browser = _BrowserInput(websocket)

    async def active() -> bool:
        match = await asyncio.to_thread(_active_generation, ledger, job_id, time())
        return match is not None and match[0] == generation and time() < min(match[1], expires_at)

    async def monitor() -> int:
        while await active():
            await asyncio.sleep(_LIFECYCLE_INTERVAL)
        return 1008

    async def transfer() -> int:
        width, height = await asyncio.wait_for(
            _handshake(websocket, browser, reader, writer),
            _IO_TIMEOUT,
        )

        async def from_browser() -> int:
            while time() < expires_at:
                message = await _client_message(browser.read, width, height)
                if time() >= expires_at:
                    break
                if message is not None:
                    writer.write(message)
                    await asyncio.wait_for(writer.drain(), _IO_TIMEOUT)
            return 1008

        async def to_browser() -> int:
            while block := await reader.read(_MAX_WS_MESSAGE):
                if time() >= expires_at:
                    return 1008
                await asyncio.wait_for(websocket.send_bytes(block), _IO_TIMEOUT)
            return 1000

        return await _first_finished(from_browser(), to_browser())

    # Monitor even while handshake or data reads are blocked.
    return await _first_finished(monitor(), transfer())


async def _first_finished(*relays: Awaitable[int]) -> int:
    tasks = [asyncio.ensure_future(relay) for relay in relays]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return max(task.result() for task in done)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@router.post("/internal/operator/jobs/{job_id}/novnc/grant")
def issue_console_grant(
    job_id: str, request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> JSONResponse:
    if not _enabled(settings):
        raise HTTPException(404)
    bearer = "Bearer " + settings.novnc_operator_token.get_secret_value()
    if not hmac.compare_digest(request.headers.get("authorization", "").encode(), bearer.encode()):
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    ledger = get_ledger(settings)
    if not _valid_job_id(job_id) or ledger.get_job(job_id) is None:
        raise HTTPException(404)
    now = time()
    active = _active_generation(ledger, job_id, now)
    if active is None:
        raise HTTPException(409, detail="sandbox_not_running")
    generation, deadline = active
    expires_at = int(min(now + GRANT_LIFETIME, deadline))
    try:
        _trusted_socket(Path(settings.novnc_socket_root), job_id, generation)
    except (OSError, ValueError) as exc:
        raise HTTPException(409, detail="console_unavailable") from exc
    if expires_at <= time():
        raise HTTPException(409, detail="sandbox_not_running")
    grant = _grant(settings.novnc_token_secret.get_secret_value(), job_id, generation, expires_at)
    return JSONResponse(
        {
            "ws_path": f"/api/jobs/{job_id}/novnc",
            "grant": _GRANT_PREFIX + grant,
            "expires_at": expires_at,
            "view_only": True,
        },
        headers={"Cache-Control": "no-store"},
    )


async def _deny(websocket: WebSocket, status: int) -> None:
    if "websocket.http.response" in websocket.scope.get("extensions", {}):
        detail = "sandbox_not_running" if status == 409 else "console_unavailable"
        await websocket.send_denial_response(JSONResponse({"code": detail}, status_code=status))
    else:
        await websocket.close(code=1008)


@router.websocket("/api/jobs/{job_id}/novnc")
async def view_console(
    job_id: str, websocket: WebSocket, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    if not _enabled(settings) or not _valid_job_id(job_id):
        await _deny(websocket, 404)
        return
    if websocket.headers.getlist("origin") != [settings.novnc_allowed_origin]:
        await _deny(websocket, 403)
        return
    protocols = websocket.scope.get("subprotocols", [])
    grants = [
        value.removeprefix(_GRANT_PREFIX) for value in protocols if value.startswith(_GRANT_PREFIX)
    ]
    grant = None
    if "binary" in protocols and len(grants) == 1:
        grant = _verify_grant(
            settings.novnc_token_secret.get_secret_value(), job_id, grants[0], time()
        )
    if grant is None:
        await _deny(websocket, 403)
        return

    generation, expires_at = grant
    ledger = get_ledger(settings)
    if await asyncio.to_thread(ledger.get_job, job_id) is None:
        await _deny(websocket, 404)
        return
    active = await asyncio.to_thread(_active_generation, ledger, job_id, time())
    if active is None or active[0] != generation:
        await _deny(websocket, 409)
        return
    try:
        path = _trusted_socket(Path(settings.novnc_socket_root), job_id, generation)
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), _IO_TIMEOUT)
    except (OSError, ValueError, asyncio.TimeoutError):
        await _deny(websocket, 409)
        return

    code = 1011
    try:
        # Recheck after connecting. A socket might remain on disk during generation replacement.
        active = await asyncio.to_thread(_active_generation, ledger, job_id, time())
        if active is None or active[0] != generation or time() >= min(active[1], expires_at):
            await _deny(websocket, 409)
            return
        await websocket.accept(subprotocol="binary")
        code = await _relay(websocket, reader, writer, ledger, job_id, generation, expires_at)
    except WebSocketDisconnect:
        return
    except RfbProtocolError:
        code = 1002
    except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError):
        pass
    finally:
        writer.close()
        with suppress(OSError, asyncio.TimeoutError):
            await asyncio.wait_for(writer.wait_closed(), _IO_TIMEOUT)
    with suppress(WebSocketDisconnect, OSError):
        await websocket.close(code=code)
