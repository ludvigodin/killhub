"""Unit tests for the acceptance evidence helpers (no live deployment, no SSH).

These prove the negative cases the acceptance suite relies on: a failed SSH run,
garbage inventory, or a retained test VM can never pass host cleanup validation.

    explore/.venv/bin/python -m pytest acceptance/test_evidence_helpers.py
"""

from __future__ import annotations

import json
import subprocess

import pytest
from evidence import (
    HostEvidenceError,
    Observation,
    check_generations,
    check_observed_transitions,
    check_receipt_before_terminal,
    check_resume,
    check_stitched_stream,
    expected_vm_names,
    fetch_host_inventory,
    job_vm_name,
    parse_inventory,
    parse_sse,
    replaced_lifecycle_events,
    retained_vms,
    sibling_vm_prefix,
    validate_operator_evidence,
    verify_host_cleanup,
)

JOB = "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
OTHER = "ffffffff-1111-2222-3333-444444444444"


def runner(
    stdout: str = "[]", returncode: int = 0, stderr: str = "", raises: Exception | None = None
):
    def run(cmd, **kwargs):
        if raises:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    return run


def inventory(*names: str) -> str:
    return json.dumps([{"name": n, "status": "running"} for n in names])


# --- host cleanup: positive and negative ---------------------------------------------


def test_clean_host_passes() -> None:
    ev = verify_host_cleanup("h", [JOB], {}, runner=runner(inventory("unrelated-vm")))
    assert ev.ok and ev.returncode == 0 and ev.names == {"unrelated-vm"}


def test_empty_but_valid_inventory_passes() -> None:
    assert verify_host_cleanup("h", [JOB], {}, runner=runner("[]")).ok


def test_failed_ssh_cannot_pass_even_with_empty_stdout() -> None:
    with pytest.raises(HostEvidenceError, match="unavailable"):
        verify_host_cleanup("h", [JOB], {}, runner=runner("", returncode=255, stderr="refused"))


def test_failed_ssh_cannot_pass_even_with_clean_looking_stdout() -> None:
    """The old check read stdout only; a non-zero exit with valid JSON must still fail."""
    with pytest.raises(HostEvidenceError) as exc:
        verify_host_cleanup("h", [JOB], {}, runner=runner("[]", returncode=1))
    assert exc.value.evidence is not None and exc.value.evidence.returncode == 1


@pytest.mark.parametrize("stdout", ["", "   \n", "no sandboxes", "[1, 2]", '[{"id": "x"}]', "{}"])
def test_invalid_inventory_cannot_pass(stdout: str) -> None:
    with pytest.raises(HostEvidenceError):
        verify_host_cleanup("h", [JOB], {}, runner=runner(stdout))


def test_ssh_not_runnable_or_timeout_cannot_pass() -> None:
    for exc in (FileNotFoundError("ssh"), subprocess.TimeoutExpired("ssh", 60)):
        with pytest.raises(HostEvidenceError, match="unavailable"):
            verify_host_cleanup("h", [JOB], {}, runner=runner(raises=exc))


def test_retained_job_vm_cannot_pass() -> None:
    with pytest.raises(HostEvidenceError, match="still on host") as exc:
        verify_host_cleanup("h", [JOB], {}, runner=runner(inventory(job_vm_name(JOB))))
    assert exc.value.evidence.retained == [job_vm_name(JOB)]


def test_retained_containment_sibling_vm_cannot_pass() -> None:
    sib = sibling_vm_prefix(JOB)
    assert sib.startswith("kh-sib-")
    with pytest.raises(HostEvidenceError, match="still on host"):
        verify_host_cleanup("h", [JOB], {}, runner=runner(inventory(sib)))
    # Suffixed variants of the probe VM name are matched by prefix too.
    with pytest.raises(HostEvidenceError, match="still on host"):
        verify_host_cleanup("h", [JOB], {}, runner=runner(inventory(sib + "-x")))


def test_retained_prior_generation_vm_cannot_pass() -> None:
    snap = {
        "receipt": {
            "dossier": {
                "sandbox_generations": [
                    {"generation": 1, "environment_id": "kh-old-bootstrap-gen"},
                    {"generation": 2, "environment_id": job_vm_name(JOB)},
                ]
            }
        }
    }
    assert "kh-old-bootstrap-gen" in expected_vm_names(JOB, snap)
    with pytest.raises(HostEvidenceError, match="kh-old-bootstrap-gen"):
        verify_host_cleanup(
            "h", [JOB], {JOB: snap}, runner=runner(inventory("kh-old-bootstrap-gen"))
        )


def test_retained_cancel_job_vm_cannot_pass() -> None:
    """Cancel jobs are verified exactly like scenario jobs once their ids are passed in."""
    with pytest.raises(HostEvidenceError, match="still on host"):
        verify_host_cleanup("h", [JOB, OTHER], {}, runner=runner(inventory(job_vm_name(OTHER))))


def test_other_jobs_vms_are_not_ours() -> None:
    assert retained_vms({job_vm_name(OTHER), "kh-sib-zzzz"}, [JOB], {}) == []


def test_no_job_ids_is_vacuous_and_fails() -> None:
    with pytest.raises(HostEvidenceError, match="vacuous"):
        verify_host_cleanup("h", [], {}, runner=runner("[]"))


def test_fetch_records_command_and_returncode() -> None:
    ev = fetch_host_inventory("h", command="echo x", runner=runner(inventory("a")))
    assert ev.command == "echo x" and ev.to_json()["inventory_names"] == ["a"]


def test_parse_inventory_accepts_wrapped_rows() -> None:
    assert parse_inventory('{"sandboxes": [{"name": "a"}]}') == {"a"}


# --- receipt before terminal -----------------------------------------------------------


def _status_event(status: str, ts: str) -> dict:
    return {"id": "9", "type": "status", "data": {"status": status, "timestamp": ts}}


def test_receipt_before_terminal_ok() -> None:
    snap = {"status": "completed", "receipt": {"dossier": {"at": "2026-11-27T10:00:00+00:00"}}}
    events = [_status_event("completed", "2026-11-27T10:00:01+00:00")]
    assert check_receipt_before_terminal(snap, events) == []


def test_receipt_after_terminal_is_flagged() -> None:
    snap = {"status": "completed", "receipt": {"dossier": {"at": "2026-11-27T10:00:05Z"}}}
    events = [_status_event("completed", "2026-11-27T10:00:01+00:00")]
    assert "after terminal" in check_receipt_before_terminal(snap, events)[0]


def test_terminal_without_receipt_or_event_is_flagged() -> None:
    assert check_receipt_before_terminal({"status": "failed", "receipt": None}, [])
    snap = {"status": "failed", "receipt": {"dossier": {"outcome": "failed"}}}
    assert check_receipt_before_terminal(snap, [])  # no terminal event


def test_cancel_dossier_without_at_relies_on_observed_transitions() -> None:
    snap = {"status": "cancelled", "receipt": {"dossier": {"outcome": "cancelled"}}}
    assert (
        check_receipt_before_terminal(snap, [_status_event("cancelled", "2026-11-27T10:00:00Z")])
        == []
    )


def test_observed_terminal_without_receipt_is_flagged() -> None:
    obs = [
        Observation("j", "finalizing", False),
        Observation("j", "completed", False),
        Observation("k", "failed", True),
    ]
    assert len(check_observed_transitions(obs)) == 1
    assert check_observed_transitions(obs[:1] + obs[2:]) == []


# --- SSE cursor ------------------------------------------------------------------------


def test_parse_sse_ignores_keepalives() -> None:
    body = (
        ": keepalive\n\n"
        'id: 1\nevent: log\ndata: {"a":1}\n\n'
        'id: 2\nevent: status\ndata: {"status":"x"}\n\n'
    )
    events = parse_sse(body)
    assert [e["id"] for e in events] == ["1", "2"] and events[1]["data"]["status"] == "x"


def test_resume_exact_ok() -> None:
    assert check_resume([1, 2, 3, 4, 5], [4, 5], 3) == []


def test_resume_missing_duplicate_and_early_are_flagged() -> None:
    assert any("missing" in p for p in check_resume([1, 2, 3, 4, 5], [4], 3))
    assert any("duplicate" in p for p in check_resume([1, 2, 3, 4, 5], [4, 4, 5], 3))
    assert any("at or before" in p for p in check_resume([1, 2, 3, 4, 5], [3, 4, 5], 3))


def test_stitched_stream() -> None:
    assert check_stitched_stream([1, 2, 3], [4, 5], [1, 2, 3, 4, 5]) == []
    assert check_stitched_stream([1, 2, 3], [3, 4, 5], [1, 2, 3, 4, 5])  # duplicate
    assert check_stitched_stream([1, 2, 3], [5], [1, 2, 3, 4, 5])  # lost 4


# --- generations / operator evidence ----------------------------------------------------


def test_generations() -> None:
    ok = [
        {"generation": 1, "state": "replaced", "destroyed_at": "t"},
        {"generation": 2, "state": "destroyed", "destroyed_at": "t"},
    ]
    assert check_generations(ok) == []
    live_old = [{"generation": 1, "state": "running"}, ok[1] | {"generation": 2}]
    assert check_generations(live_old)
    assert check_generations([ok[0], {"generation": 2, "state": "running"}])
    assert check_generations([])
    assert check_generations([{"generation": 2, "state": "destroyed", "destroyed_at": "t"}])


def test_replaced_lifecycle_events() -> None:
    ev = [{"type": "lifecycle", "data": {"payload": {"phase": "replaced", "generation": 2}}}]
    assert replaced_lifecycle_events(ev) == [2]


def test_operator_evidence_validation() -> None:
    entry = {
        "operator": "me",
        "observed_at": "2026-11-27T10:00:00Z",
        "result": "pass",
        "job_ids": ["j"],
        "host_evidence": "ssh msb list: none",
    }
    assert (
        validate_operator_evidence({"restart_recovery": entry, "host_expiry_cp_stopped": entry})
        == []
    )
    assert validate_operator_evidence({"restart_recovery": entry})
    assert validate_operator_evidence(
        {"restart_recovery": entry, "host_expiry_cp_stopped": entry | {"result": "fail"}}
    )
    assert validate_operator_evidence([])
