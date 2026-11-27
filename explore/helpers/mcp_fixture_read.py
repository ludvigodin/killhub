"""Measure a single read_text_file call against the pinned filesystem build in Plane 2."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

from mcp_stdio_verify import _read_ndjson, _write_ndjson


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fixture_read(launch: list[str], directory: Path, timeout: float = 15) -> dict:
    """Observe one read on a fresh fixture directory served by the pinned build."""
    marker = directory / "sample.txt"
    content = secrets.token_hex(32).encode("ascii")
    marker.write_bytes(content)
    expected = _digest(content)
    started = time.monotonic()
    deadline = started + timeout
    evidence = {
        "tool": "read_text_file",
        "expected_sha256": expected,
        "timeout_ms": int(timeout * 1000),
    }
    with subprocess.Popen(
        [*launch, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    ) as proc:

        def request(seq: int, method: str, params: dict) -> dict:
            _write_ndjson(proc, {"jsonrpc": "2.0", "id": seq, "method": method, "params": params})
            while True:
                msg = _read_ndjson(proc, deadline - time.monotonic())
                if isinstance(msg, dict) and "method" in msg and "id" not in msg:
                    continue
                if (
                    msg.get("jsonrpc") != "2.0"
                    or msg.get("id") != seq
                    or not isinstance(msg.get("result"), dict)
                ):
                    raise ValueError("invalid_response")
                return msg["result"]

        try:
            init = request(
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "killhub-fixture-read", "version": "1"},
                },
            )
            if not init.get("protocolVersion"):
                raise ValueError("missing_protocol")
            _write_ndjson(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            tools = request(2, "tools/list", {}).get("tools", [])
            tool = next(
                (t for t in tools if isinstance(t, dict) and t.get("name") == "read_text_file"), {}
            )
            if not isinstance(tool.get("inputSchema"), dict):
                raise ValueError("tool_schema_unavailable")
            evidence["schema_sha256"] = _digest(
                json.dumps(tool["inputSchema"], sort_keys=True).encode()
            )
            result = request(
                3, "tools/call", {"name": "read_text_file", "arguments": {"path": str(marker)}}
            )
            blocks = result.get("content")
            if result.get("isError") or not isinstance(blocks, list) or len(blocks) != 1:
                raise ValueError("missing_read_result")
            block = blocks[0]
            if block.get("type") != "text" or not isinstance(block.get("text"), str):
                raise ValueError("missing_text")
            evidence["response_sha256"] = _digest(block["text"].encode())
        finally:
            proc.kill()
            proc.wait()
    elapsed = int((time.monotonic() - started) * 1000)
    # Read at most one byte beyond the expected size; a larger file cannot match.
    intact = not marker.is_symlink() and marker.is_file() and list(directory.iterdir()) == [marker]
    if intact:
        with marker.open("rb") as f:
            intact = _digest(f.read(len(content) + 1)) == expected
    evidence.update(fixture_unchanged=intact, elapsed_ms=elapsed)
    evidence["status"] = (
        "passed"
        if intact and evidence["response_sha256"] == expected and elapsed <= timeout * 1000
        else "failed"
    )
    return evidence


if __name__ == "__main__":
    try:
        with tempfile.TemporaryDirectory(prefix="killhub-read-") as directory:
            result = fixture_read(
                ["node", "/tmp/killhub/repo/src/filesystem/dist/index.js"], Path(directory)
            )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        result = {"status": "partial", "reason": type(exc).__name__}
    print(json.dumps(result))
