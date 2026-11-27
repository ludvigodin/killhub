"""Plane 1 tests for bounded, generation-scoped telemetry frames."""

import json

import pytest

from ipc_telemetry import (
    MAX_LINE_BYTES,
    TelemetryBinding,
    TelemetryFrameError,
    ingest_ndjson,
)


def frame(**updates):
    value = {
        "job_id": "job-1",
        "generation": 2,
        "sequence": 1,
        "sensor": "strace",
        "observed_at": "2026-11-27T16:00:00Z",
        "summary": "synthetic syscall observation",
        "counters": {"flagged": 1},
        "observation_id": "obs-1",
    }
    value.update(updates)
    return json.dumps(value).encode() + b"\n"


def test_ingests_only_matching_bounded_frames():
    saved = []
    count = ingest_ndjson(
        [frame(), frame(sequence=2)],
        binding=TelemetryBinding("job-1", 2),
        persist=saved.extend,
    )
    assert count == 2
    assert [item["sequence"] for item in saved] == [1, 2]


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (frame(job_id="other"), "binding_mismatch"),
        (frame(generation=3), "binding_mismatch"),
        (frame(sensor="unknown"), "invalid_sensor"),
        (frame(sequence=True), "invalid_sequence"),
        (frame(extra="host_path"), "invalid_fields"),
        (frame(summary="x" * 5000), "invalid_summary"),
        (frame(counters={"bad": -1}), "invalid_counters"),
        (b"{bad}\n", "invalid_json"),
        (frame()[:-1], "unterminated_line"),
        (b"x" * (MAX_LINE_BYTES + 1) + b"\n", "line_too_large"),
    ],
)
def test_rejects_invalid_frames_without_persistence(raw, reason):
    saved = []
    with pytest.raises(TelemetryFrameError, match=reason):
        ingest_ndjson([raw], binding=TelemetryBinding("job-1", 2), persist=saved.extend)
    assert saved == []


def test_rejects_out_of_order_or_duplicate_sequence_atomically():
    saved = []
    with pytest.raises(TelemetryFrameError, match="sequence_order"):
        ingest_ndjson(
            [frame(sequence=2), frame(sequence=2)],
            binding=TelemetryBinding("job-1", 2),
            persist=saved.extend,
        )
    assert saved == []
