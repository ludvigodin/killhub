"""Explicit cancel (D61): DELETE -> cancelled, sandbox destroyed, receipt written.

Besides the mid-run case, cancellation is exercised at each pipeline boundary the
job status exposes: create (``provisioning``), install (``installing``), verify
(``verifying``) and finalize (``finalizing``). Every cancel job is registered so the
host cleanup check (including kh-sib-* probe VMs and all generations) covers it.
"""

from __future__ import annotations

import time

import pytest
from conftest import (
    REGISTRY,
    TERMINAL,
    evidence_unavailable,
    snapshot,
    submit,
    wait_terminal,
)
from evidence import check_generations, check_receipt_before_terminal, parse_sse

pytestmark = pytest.mark.slow

CANCEL_REPO = "https://github.com/mokafari/killhub-sca-npm-control-20261127"
# Has real install and verify phases, so every boundary is reachable.
BOUNDARY_REPO = "https://github.com/heroku/nodejs-getting-started"

# Ordered pipeline statuses (API.md job state machine); boundary -> status to cancel in.
_ORDER = ["pending", "queued", "analyzing", "planning", "provisioning", "installing", "verifying"]
_ORDER += ["repairing", "scanning", "finalizing"]
BOUNDARIES = {
    "create": "provisioning",
    "install": "installing",
    "verify": "verifying",
    "finalize": "finalizing",
}


def _rank(status: str) -> int:
    return _ORDER.index(status) if status in _ORDER else len(_ORDER)


def _assert_cancelled(client, jid: str, label: str) -> dict:
    final = wait_terminal(client, {label: jid}, timeout=600)[label]
    assert final["status"] == "cancelled", (final["status"], final.get("error"))
    assert final.get("cancel_requested_at")
    assert (final.get("receipt") or {}).get("dossier"), "cancel must still write a receipt"
    if final.get("sandbox_id"):
        assert (final.get("cleanup") or {}).get("status") == "destroyed", final.get("cleanup")
        assert final.get("destroyed_at"), "destroyed_at missing after confirmed removal"
    gens = ((final.get("receipt") or {}).get("dossier") or {}).get("sandbox_generations")
    if gens:
        destroyed = (final.get("cleanup") or {}).get("status") == "destroyed"
        assert not check_generations(gens, destroyed=destroyed), gens
    # Receipt-before-terminal from persisted events (no timestamp on cancel dossiers:
    # the tight polling in snapshot() covers ordering via observed transitions).
    r = client.get(f"/api/jobs/{jid}/events", timeout=60)
    assert r.status_code == 200
    events = parse_sse(r.text)
    assert not check_receipt_before_terminal(final, events), check_receipt_before_terminal(
        final, events
    )
    # Idempotent: a second cancel returns the same terminal snapshot.
    again = client.delete(f"/api/jobs/{jid}")
    assert again.status_code == 200
    assert snapshot(client, jid)["status"] == "cancelled"
    return final


def test_cancel_mid_run(client) -> None:
    jid = submit(client, CANCEL_REPO, "cancel:mid_run")
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:  # cancel once it is actually doing work
        if snapshot(client, jid)["status"] not in {"pending", "queued"}:
            break
        time.sleep(5)
    r = client.delete(f"/api/jobs/{jid}")
    assert r.status_code == 200, r.text[:300]
    _assert_cancelled(client, jid, "cancel")


@pytest.mark.parametrize("boundary", list(BOUNDARIES), ids=list(BOUNDARIES))
def test_cancel_at_pipeline_boundary(client, boundary: str) -> None:
    """DELETE the instant the job reports the boundary status, then check the D61 contract."""
    target = BOUNDARIES[boundary]
    jid = submit(client, BOUNDARY_REPO, f"cancel:{boundary}")
    deadline = time.monotonic() + 1800
    seen = None
    while time.monotonic() < deadline:
        status = snapshot(client, jid)["status"]
        if status == target:
            seen = status
            break
        if status in TERMINAL or _rank(status) > _rank(target):
            break
        time.sleep(1)
    if seen is None:
        # Clean up whatever is running, then report the boundary as unproven.
        client.delete(f"/api/jobs/{jid}")
        wait_terminal(client, {boundary: jid}, timeout=900)
        evidence_unavailable(f"job moved past '{target}' before it could be cancelled there")
    r = client.delete(f"/api/jobs/{jid}")
    assert r.status_code == 200, r.text[:300]
    final = wait_terminal(client, {boundary: jid}, timeout=900)[boundary]
    if final["status"] != "cancelled" and not final.get("cancel_requested_at"):
        # The job reached its terminal state before the cancel landed (finalize race).
        evidence_unavailable(f"job finished before cancel landed at '{target}'")
    final = _assert_cancelled(client, jid, boundary)
    REGISTRY.notes.setdefault("cancel_boundaries", {})[boundary] = {
        "job_id": jid,
        "cancelled_in": target,
        "final_status": final["status"],
    }
