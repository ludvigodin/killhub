"""Minimal stdio MCP shim for OpenCode → Killhub harness tools (D38).

OpenCode trusted config points only at this server. Tools are job-scoped via
KILLHUB_JOB_ID. This is a thin JSON-RPC loop so the agent never gets host shell.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from harness_tools import HarnessTools


def _read_message() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _tools_list() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": f"Killhub harness tool: {name}",
            "inputSchema": {"type": "object", "additionalProperties": True},
        }
        for name in sorted(HarnessTools.ALLOWED)
    ]


def main() -> int:
    job_id = (os.environ.get("KILLHUB_JOB_ID") or "").strip()
    if not job_id:
        sys.stderr.write("KILLHUB_JOB_ID is required\n")
        return 2
    tools = HarnessTools(job_id)

    while True:
        msg = _read_message()
        if msg is None:
            break
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "killhub-harness", "version": "0.1"},
                    },
                }
            )
            continue
        if method == "notifications/initialized":
            continue
        if method == "tools/list":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": _tools_list()},
                }
            )
            continue
        if method == "tools/call":
            name = str(params.get("name") or "")
            args = params.get("arguments") or {}
            try:
                result = tools.call(name, **args) if isinstance(args, dict) else tools.call(name)
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {"type": "text", "text": json.dumps(result)},
                            ]
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001 — surface to agent
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )
            continue
        if req_id is not None:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
