"""Explicit cancel (D61): DELETE → cancelled, sandbox destroyed, receipt written."""

from __future__ import annotations

import time

import pytest
from conftest import snapshot, submit, wait_terminal

pytestmark = pytest.mark.slow

CANCEL_REPO = "https://github.com/mokafari/killhub-sca-npm-control-20261127"


def test_cancel_mid_run(client) -> None:
    jid = submit(client, CANCEL_REPO)
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:  # cancel once it is actually doing work
        if snapshot(client, jid)["status"] not in {"pending", "queued"}:
            break
        time.sleep(5)
    r = client.delete(f"/api/jobs/{jid}")
    assert r.status_code == 200, r.text[:300]
    final = wait_terminal(client, {"cancel": jid}, timeout=600)["cancel"]
    assert final["status"] == "cancelled", (final["status"], final.get("error"))
    assert final.get("cancel_requested_at")
    assert (final.get("receipt") or {}).get("dossier"), "cancel must still write a receipt"
    if final.get("sandbox_id"):
        assert (final.get("cleanup") or {}).get("status") == "destroyed", final.get("cleanup")
    # Idempotent: a second cancel returns the same terminal snapshot.
    again = client.delete(f"/api/jobs/{jid}")
    assert again.status_code == 200
    assert snapshot(client, jid)["status"] == "cancelled"
