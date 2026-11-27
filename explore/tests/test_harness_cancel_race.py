"""Cancel landing while `msb create` is in flight must not leave an untracked VM.

Seen live on killhub.pro: the cancel finalizer closed the job (cleanup
destroyed) while create was running; the new VM could not be recorded
(cancel-frozen ledger) and kept running until the orphan reaper found it.
"""

from __future__ import annotations

from typing import Sequence

import pytest

from harness import CliResult, EnvironmentPlan, MsbCli, create_environment, environment_name_for_job
from jobs import get_ledger


def test_vm_created_after_cancel_is_removed(client, monkeypatch) -> None:
    _ = client
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    ledger = get_ledger(cfg)
    job = ledger.create_job("https://github.com/example/cancel-race", env_ttl_seconds=3600)
    name = environment_name_for_job(job.job_id)
    calls: list[str] = []
    removed = {"done": False}

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        _ = timeout
        cmd = argv[1] if len(argv) > 1 else ""
        calls.append(cmd)
        if cmd == "create":
            # The user's DELETE lands while the VM is booting.
            ledger.update_job_fields(job.job_id, cancel_requested_at="2026-11-27T17:51:35Z")
            return CliResult(tuple(argv), 0, "created", "")
        if cmd == "remove":
            removed["done"] = True
            return CliResult(tuple(argv), 0, "removed", "")
        if cmd == "status":
            if removed["done"]:
                return CliResult(tuple(argv), 1, "", f"error: sandbox not found: {name}")
            return CliResult(tuple(argv), 0, f"{name} running", "")
        return CliResult(tuple(argv), 0, "", "")

    with pytest.raises(Exception, match="cancel"):
        create_environment(
            job.job_id,
            EnvironmentPlan(image="debian", cpus=1, memory="512M"),
            settings=cfg,
            cli=MsbCli(cfg, runner=runner),
        )

    assert "remove" in calls, calls
    assert ledger.list_sandbox_generations(job.job_id) == []
    events = [e for e in ledger.list_events(job.job_id) if e.type == "lifecycle"]
    removal = [e for e in events if e.message == "untracked sandbox removed"]
    assert removal and removal[0].payload["confirmed"] is True
    assert removal[0].payload["environment_id"] == name
    get_settings.cache_clear()
