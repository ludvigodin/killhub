"""Operator-facing Killhub MCP (stdio) — wraps the public Jobs API (D81).

Distinct from ``harness_mcp`` (Environment Agent → Plane 2). Shared tool logic
lives in ``operator_mcp_tools`` (also used by HTTP ``POST /internal/mcp``).

Env:
  KILLHUB_BASE_URL   default https://killhub.pro  (local: http://127.0.0.1:3000)
  KILLHUB_API_TOKEN  optional Bearer token (unused on anonymous public demo)
"""

from __future__ import annotations

import json
import sys
from typing import Any

from operator_mcp_tools import (
    CREATE_AND_WAIT_TIMEOUT,
    DEFAULT_BASE_URL,
    DEFAULT_POLL_SECONDS,
    DEFAULT_WAIT_TIMEOUT,
    MAX_CREATE_JOBS,
    TERMINAL_STATUSES,
    TOOL_NAMES,
    KillhubApiError,
    KillhubJobsClient,
    call_tool,
    client_from_env,
    handle_jsonrpc,
    load_public_fixtures,
    resolve_public_fixture,
    resolve_ui_url,
    summarize_receipt,
    summarize_status,
    tools_list,
)

__all__ = [
    "CREATE_AND_WAIT_TIMEOUT",
    "DEFAULT_BASE_URL",
    "DEFAULT_POLL_SECONDS",
    "DEFAULT_WAIT_TIMEOUT",
    "MAX_CREATE_JOBS",
    "TERMINAL_STATUSES",
    "TOOL_NAMES",
    "KillhubApiError",
    "KillhubJobsClient",
    "call_tool",
    "load_public_fixtures",
    "main",
    "resolve_public_fixture",
    "resolve_ui_url",
    "summarize_receipt",
    "summarize_status",
    "tools_list",
]


def _read_message() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    return json.loads(line)


def _write_message(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> int:
    client = client_from_env()
    try:
        while True:
            msg = _read_message()
            if msg is None:
                break
            response = handle_jsonrpc(client, msg)
            if response is not None:
                _write_message(response)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
