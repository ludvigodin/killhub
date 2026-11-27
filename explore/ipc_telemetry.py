"""Plane 1 bounded guest IPC frame validation.

The trusted AF_VSOCK/UDS listener supplies job and generation identity. This
module accepts only bounded NDJSON evidence for that binding and passes parsed
records to a host-owned persistence callback.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

MAX_LINE_BYTES = 65_536
MAX_RECORDS_PER_BATCH = 256
_ALLOWED_FIELDS = frozenset(
    {
        "job_id",
        "generation",
        "sequence",
        "sensor",
        "observed_at",
        "summary",
        "counters",
        "observation_id",
    }
)
_ALLOWED_SENSORS = frozenset(
    {
        "mitmdump_http",
        "mitmdump_dns",
        "doh_dot_quic_drop",
        "canary_block",
        "strace",
        "overlayfs",
        "mcp_wire_tap",
        "cgroup_v2",
        "kill_switch",
        "telemetry",
    }
)


class TelemetryFrameError(ValueError):
    """A guest frame failed the bounded, job-scoped telemetry contract."""


@dataclass(frozen=True)
class TelemetryBinding:
    """Identity authenticated by the host management transport."""

    job_id: str
    generation: int


def _parse_line(raw: bytes, binding: TelemetryBinding) -> dict[str, Any]:
    if len(raw) > MAX_LINE_BYTES:
        raise TelemetryFrameError("line_too_large")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TelemetryFrameError("invalid_json") from exc
    if not isinstance(value, dict) or set(value) - _ALLOWED_FIELDS:
        raise TelemetryFrameError("invalid_fields")
    if value.get("job_id") != binding.job_id or value.get("generation") != binding.generation:
        raise TelemetryFrameError("binding_mismatch")
    if type(value.get("sequence")) is not int or value["sequence"] < 0:
        raise TelemetryFrameError("invalid_sequence")
    if value.get("sensor") not in _ALLOWED_SENSORS:
        raise TelemetryFrameError("invalid_sensor")
    if not isinstance(value.get("observed_at"), str) or not value["observed_at"]:
        raise TelemetryFrameError("invalid_timestamp")
    if not isinstance(value.get("summary"), str) or len(value["summary"].encode()) > 4096:
        raise TelemetryFrameError("invalid_summary")
    counters = value.get("counters", {})
    if not isinstance(counters, dict) or len(counters) > 32:
        raise TelemetryFrameError("invalid_counters")
    if any(
        not isinstance(key, str) or type(item) is not int or item < 0
        for key, item in counters.items()
    ):
        raise TelemetryFrameError("invalid_counters")
    observation_id = value.get("observation_id")
    if observation_id is not None and (
        not isinstance(observation_id, str) or len(observation_id) > 128
    ):
        raise TelemetryFrameError("invalid_observation_id")
    return value


def ingest_ndjson(
    chunks: list[bytes],
    *,
    binding: TelemetryBinding,
    persist: Callable[[list[dict[str, Any]]], None],
) -> int:
    """Validate one bounded batch fully before a single host persistence call."""
    if not chunks or len(chunks) > MAX_RECORDS_PER_BATCH:
        raise TelemetryFrameError("invalid_batch_size")
    records: list[dict[str, Any]] = []
    for chunk in chunks:
        if not chunk.endswith(b"\n"):
            raise TelemetryFrameError("unterminated_line")
        records.append(_parse_line(chunk[:-1], binding))
    sequences = [record["sequence"] for record in records]
    if sequences != sorted(set(sequences)):
        raise TelemetryFrameError("sequence_order")
    persist(records)
    return len(records)
