#!/usr/bin/env python3
"""Plane 2 MCP stdio readiness and read-only fixture inventory (D51, D63).

Launches a subprocess from argv after `--`, speaks JSON-RPC over stdio.
Supports newline-delimited JSON (NDJSON) used by current MCP filesystem
servers, with optional Content-Length framing via `--framing content-length`.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import sys
import time
from collections.abc import Callable

_MAX_MESSAGE_BYTES = 2_000_000
_MAX_INVENTORY_PAGES = 4
_MAX_INVENTORY_ENTRIES = 256
_INVENTORY_TIMEOUT = 8


def collect_inventory(
    capabilities: dict,
    first_tools: dict,
    request: Callable[[str, dict], dict],
) -> dict:
    """Return stable hashes and counts without surfacing guest descriptions or schemas."""
    inventory = {}
    for collection, primary_key in (("tools", "name"), ("resources", "uri"), ("prompts", "name")):
        if collection != "tools" and collection not in capabilities:
            inventory[collection] = {"status": "unsupported"}
            continue

        method = f"{collection}/list"
        entries = {}
        cursors = set()
        try:
            page = first_tools if collection == "tools" else request(method, {})
            for page_number in range(_MAX_INVENTORY_PAGES):
                items = page.get(collection)
                if (
                    not isinstance(items, list)
                    or len(entries) + len(items) > _MAX_INVENTORY_ENTRIES
                ):
                    raise ValueError("invalid or oversized inventory")
                for item in items:
                    key = item.get(primary_key) if isinstance(item, dict) else None
                    if not isinstance(key, str) or not key or key in entries:
                        raise ValueError("invalid or duplicate inventory identity")
                    entries[key] = item
                cursor = page.get("nextCursor")
                if cursor is None:
                    break
                if (
                    not isinstance(cursor, str)
                    or not cursor
                    or len(cursor) > 1024
                    or cursor in cursors
                    or page_number + 1 == _MAX_INVENTORY_PAGES
                ):
                    raise ValueError("invalid or incomplete inventory pagination")
                cursors.add(cursor)
                page = request(method, {"cursor": cursor})

            # Sort by identity, then sort object keys. The digest includes each
            # complete metadata record but the records stay inside the guest.
            data = json.dumps(
                [entries[key] for key in sorted(entries)],
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            inventory[collection] = {
                "status": "recorded",
                "count": len(entries),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        except (TimeoutError, ValueError, TypeError, RecursionError, OSError):
            inventory[collection] = {"status": "unavailable"}
    return inventory


def _write_ndjson(proc: subprocess.Popen[bytes], msg: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(msg).encode("utf-8") + b"\n")
    proc.stdin.flush()


def _write_content_length(proc: subprocess.Popen[bytes], msg: dict) -> None:
    assert proc.stdin is not None
    body = json.dumps(msg).encode("utf-8")
    header = (f"Content-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n").encode(
        "ascii"
    )
    proc.stdin.write(header + body)
    proc.stdin.flush()


def _read_exact(proc: subprocess.Popen[bytes], n: int, deadline: float) -> bytes:
    assert proc.stdout is not None
    buf = b""
    fd = proc.stdout.fileno()
    while len(buf) < n:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError(f"timed out reading {n} bytes (got {len(buf)})")
        ready, _, _ = select.select([fd], [], [], min(remaining, 0.5))
        if not ready:
            if proc.poll() is not None:
                err = b""
                if proc.stderr is not None:
                    err = proc.stderr.read() or b""
                raise TimeoutError(
                    f"MCP process exited ({proc.returncode}) before full read; stderr={err[:300]!r}"
                )
            continue
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            raise TimeoutError("MCP stdout closed before full read")
        buf += chunk
    return buf


def _read_ndjson(proc: subprocess.Popen[bytes], timeout: float) -> dict:
    deadline = time.time() + timeout
    line = b""
    while b"\n" not in line:
        line += _read_exact(proc, 1, deadline)
        if len(line) > _MAX_MESSAGE_BYTES:
            raise ValueError("MCP NDJSON line too large")
    return json.loads(line.decode("utf-8"))


def _read_content_length(proc: subprocess.Popen[bytes], timeout: float) -> dict:
    deadline = time.time() + timeout
    headers = b""
    while b"\r\n\r\n" not in headers:
        headers += _read_exact(proc, 1, deadline)
        if len(headers) > 65536:
            raise ValueError("MCP headers too large")
    length = None
    for line in headers.decode("latin-1").split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
            break
    if length is None or not 0 < length <= _MAX_MESSAGE_BYTES:
        raise ValueError("missing or invalid MCP Content-Length")
    body = _read_exact(proc, length, deadline)
    return json.loads(body.decode("utf-8"))


TOOLS_DUMP = "/tmp/killhub/activity/mcp_tools.json"


def _dump_tools(tools):
    """Write names/descriptions/schemas for the host tool-poisoning review (best effort)."""
    if not isinstance(tools, list) or not os.path.isdir(os.path.dirname(TOOLS_DUMP)):
        return
    slim = []
    for t in tools[:500]:
        if not isinstance(t, dict):
            continue
        slim.append(
            {
                "name": str(t.get("name") or "")[:200],
                "description": str(t.get("description") or "")[:4000],
                "input_schema_text": json.dumps(t.get("inputSchema") or {})[:4000],
            }
        )
    try:
        with open(TOOLS_DUMP, "w", encoding="utf-8") as fh:
            json.dump(slim, fh)
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if "--" not in argv:
        print(
            "usage: mcp_stdio_verify.py [--timeout N] [--allow-empty-tools] "
            "[--inventory] [--framing ndjson|content-length] -- <launch...>",
            file=sys.stderr,
        )
        return 2
    split = argv.index("--")
    opts = argv[1:split]
    launch = argv[split + 1 :]
    if not launch:
        print("launch command required after --", file=sys.stderr)
        return 2
    timeout = 20.0
    allow_empty = "--allow-empty-tools" in opts
    inventory_requested = "--inventory" in opts
    framing = "ndjson"
    if "--timeout" in opts:
        i = opts.index("--timeout")
        timeout = float(opts[i + 1])
    if "--framing" in opts:
        i = opts.index("--framing")
        framing = opts[i + 1].strip().lower()
    if framing not in {"ndjson", "content-length"}:
        print(f"unknown framing: {framing}", file=sys.stderr)
        return 2

    write = _write_ndjson if framing == "ndjson" else _write_content_length
    read = _read_ndjson if framing == "ndjson" else _read_content_length

    started = time.time()
    proc = subprocess.Popen(
        launch,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    try:
        write(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "killhub-mcp-stdio-verify",
                        "version": "0.1",
                    },
                },
            },
        )
        init = read(proc, timeout)
        write(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        write(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools_msg = read(proc, timeout)
        tools = ((tools_msg.get("result") or {}).get("tools")) or []
        _dump_tools(tools)
        tool_count = len(tools) if isinstance(tools, list) else 0
        ok = isinstance(tools, list) and (allow_empty or tool_count >= 1)
        evidence = {
            "ok": ok,
            "tool_count": tool_count,
            "tool_names": [t.get("name") for t in tools if isinstance(t, dict) and t.get("name")]
            if isinstance(tools, list)
            else [],
            "protocol": (init.get("result") or {}).get("protocolVersion"),
            "elapsed_ms": int((time.time() - started) * 1000),
            "allow_empty_tools": allow_empty,
            "framing": framing,
        }
        if ok and inventory_requested:
            # Inventory has a separate total budget and cannot change readiness.
            deadline = time.monotonic() + _INVENTORY_TIMEOUT
            request_id = 2

            def list_page(method: str, params: dict) -> dict:
                nonlocal request_id
                request_id += 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("MCP inventory deadline")
                write(
                    proc, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
                )
                response = read(proc, remaining)
                if not isinstance(response, dict) or response.get("id") != request_id:
                    raise ValueError("unexpected MCP inventory response")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise ValueError("missing MCP inventory result")
                return result

            capabilities = (init.get("result") or {}).get("capabilities")
            first_tools = tools_msg.get("result")
            if (
                init.get("id") == 1
                and tools_msg.get("id") == 2
                and isinstance(capabilities, dict)
                and isinstance(first_tools, dict)
            ):
                evidence["inventory"] = collect_inventory(capabilities, first_tools, list_page)
            else:
                evidence["inventory"] = {"status": "unavailable"}
        print(json.dumps(evidence))
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        err = ""
        try:
            if proc.stderr is not None:
                ready, _, _ = select.select([proc.stderr.fileno()], [], [], 0.1)
                if ready:
                    err = os.read(proc.stderr.fileno(), 800).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            err = ""
        print(json.dumps({"ok": False, "error": str(exc), "stderr": err[:400]}))
        return 1
    finally:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
