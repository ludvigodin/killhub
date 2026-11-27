"""Teardown confirmation, reaper cleanup, restart recovery, and claim-deadline tests.

What this module does:
    Verifies Plane 1 sandbox teardown confirmation, reaper cleanup retries,
    late terminal receipt reconciliation and checkpoint collection eligibility,
    restart recovery, bounded job TTL enforcement, and atomic pending-job
    claim/expiry handling.

Plane & trust-zone responsibility:
    Plane 1 (control-plane) test suite exercising ``Ledger``, ``harness``,
    ``reaper``, ``install``, and ``service`` against a real SQLite ledger and
    controlled ``MsbCli`` stubs; executes no Plane 2 microVM workloads.

Key contracts / invariants:
    - D57: Sandbox teardown sets ``destroyed_at`` only after synchronous
      ``remove`` confirmation or validated ``msb list --format json`` inventory.
    - D27 / D80: Generation tracking and exact-name guards isolate historical
      sandbox teardowns and prevent stopping a reused sandbox name.
    - Late cleanup reconciliation (``record_reaped_cleanup``) updates
      ``jobs`` and ``job_receipts.lifecycle`` without mutating ``dossier`` or
      ``verification``, making terminal checkpoints eligible for
      ``reap_terminal_checkpoints`` collection.
    - D41 / D82: Job lifetime is bounded to ``min(env_ttl, job_timeout)``,
      expired jobs are rejected before ``msb`` invocation, and pending jobs are
      claimed atomically at most once across concurrent workers.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier

import pytest

from config import Settings
from harness import CliResult, HarnessError, MsbCli, create_environment, destroy_environment
from install import InstallError, transition_to_verify_offline
from jobs import get_ledger, reset_ledger_for_tests
from ledger import Ledger
from models import CleanupState
from reaper import (
    reap_expired_from_host,
    reap_expired_from_ledger,
    reap_terminal_checkpoints,
    recover_interrupted_jobs,
)
from service import claim_pending_job, create_job


@pytest.mark.parametrize(
    ("inventory", "exit_code", "confirmed"),
    [
        ("", 255, False),
        ("warning: daemon restarting", 0, False),
        ('[{"name": "kh-fixture"}]', 0, False),
        ('[{"state": "running"}]', 0, False),
        ("[]", 0, True),
    ],
)
def test_remove_failure_needs_valid_inventory(
    tmp_path: Path, inventory: str, exit_code: int, confirmed: bool
) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)
    calls: list[str] = []

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        cmd = args[1]
        calls.append(cmd)
        if cmd == "list":
            return CliResult(tuple(args), exit_code, inventory, "")
        # A transport failure cannot prove either status or removal.
        return CliResult(tuple(args), 255, "", "operator transport unavailable")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        ledger.append_sandbox_generation(
            job.job_id, environment_id="kh-fixture", image="debian", expires_at=job.expires_at
        )
        result = destroy_environment(
            "kh-fixture", job_id=job.job_id, settings=cfg, cli=MsbCli(cfg, runner=run)
        )
        assert result.confirmed is confirmed
        assert calls == ["stop", "remove", "list"]
        gen = ledger.list_sandbox_generations(job.job_id)[0]
        assert gen.state == ("destroyed" if confirmed else "destroy_failed")
        assert (gen.destroyed_at is not None) is confirmed
    finally:
        reset_ledger_for_tests()


def test_historical_sandbox_destroy_does_not_mark_current_generation(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        return CliResult(tuple(args), 0, json.dumps([{"name": "kh-current"}]), "")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        for name in ("kh-historical", "kh-current"):
            ledger.append_sandbox_generation(
                job.job_id, environment_id=name, image="debian", expires_at=job.expires_at
            )
        result = destroy_environment(
            "kh-historical", job_id=job.job_id, settings=cfg, cli=MsbCli(cfg, runner=run)
        )
        assert result.confirmed
        old, current = ledger.list_sandbox_generations(job.job_id)
        assert old.destroyed_at is not None
        assert current.destroyed_at is None
        assert current.state == "provisioning"
    finally:
        reset_ledger_for_tests()


def test_expired_generation_does_not_stop_a_reused_name(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)
    calls: list[str] = []

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        calls.append(args[1])
        return CliResult(tuple(args), 0, '[{"name": "kh-current"}]', "")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        # An old row from an interrupted scale/restore must not own the reused name.
        for expiry in ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"):
            ledger.append_sandbox_generation(
                job.job_id, environment_id="kh-current", image="debian", expires_at=expiry
            )
        reap_expired_from_ledger(
            settings=cfg, cli=MsbCli(cfg, runner=run), now=datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        assert calls == ["list"]
        assert ledger.get_job(job.job_id).destroyed_at is None
    finally:
        reset_ledger_for_tests()


def test_offline_restore_requires_positive_removal_evidence(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)
    calls: list[tuple[str, ...]] = []

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        calls.append(tuple(args))
        # Even if stderr mentions a missing component, the VM is still listed.
        if args[1] == "remove":
            return CliResult(tuple(args), 1, "", "helper command not found")
        return CliResult(tuple(args), 0, '[{"name": "kh-install"}]', "")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        with pytest.raises(InstallError) as error:
            transition_to_verify_offline(
                "kh-install", job_id=job.job_id, settings=cfg, cli=MsbCli(cfg, runner=run)
            )
        assert error.value.code == "offline_remove_failed"
        assert not any(args[1:3] == ("snapshot", "restore") for args in calls)
    finally:
        reset_ledger_for_tests()


def test_reaper_retry_updates_terminal_receipt_and_checkpoint_eligibility(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)
    live = True
    may_remove = False
    checkpoints_removed: list[str] = []

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        nonlocal live
        cmd = args[1]
        if cmd == "list":
            return CliResult(tuple(args), 0, json.dumps([{"name": name}] if live else []), "")
        if cmd == "remove":
            if may_remove:
                live = False
            return CliResult(tuple(args), 0 if may_remove else 1, "", "")
        if args[1:3] == ["snapshot", "list"]:
            return CliResult(tuple(args), 0, json.dumps([{"name": checkpoint}]), "")
        if args[1:3] == ["snapshot", "remove"]:
            checkpoints_removed.append(args[-1])
        return CliResult(tuple(args), 0, "", "")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=3600)
        name = f"kh-{job.job_id}"
        checkpoint = f"kh-snap-{job.job_id.replace('-', '')}"
        gen = ledger.append_sandbox_generation(
            job.job_id, environment_id=name, image="debian", expires_at=job.expires_at
        )
        ledger.mark_generation_state(job.job_id, gen.generation, "destroy_failed")
        ledger.finalize_job(
            job.job_id,
            status="cancelled",
            cleanup=CleanupState(status="destroy_failed", attempts=1),
            receipt={
                "verification": {"kind": "setup_failed"},
                "lifecycle": {"confirmed": False, "cleanup": "destroy_failed", "cancel": True},
                "dossier": {"outcome": "cancelled"},
            },
            include_verdict=True,
        )
        original_receipt = ledger.get_receipt(job.job_id)
        cli = MsbCli(cfg, runner=run)

        # A terminal job must retry cleanup without waiting an hour for absolute expiry.
        first = reap_expired_from_ledger(settings=cfg, cli=cli)
        assert first[0]["reason"] == "cleanup_retry" and first[0]["confirmed"] is False
        assert ledger.get_job(job.job_id).destroyed_at is None
        assert reap_terminal_checkpoints(cfg, cli) == []
        reset_ledger_for_tests()
        ledger = get_ledger(cfg)

        may_remove = True
        second = reap_expired_from_ledger(settings=cfg, cli=cli)
        assert second[0]["confirmed"] is True
        refreshed = ledger.get_job(job.job_id)
        receipt = ledger.get_receipt(job.job_id)
        assert refreshed.status == "cancelled" and refreshed.cleanup.status == "destroyed"
        assert refreshed.cleanup.attempts == 3
        assert receipt["lifecycle"]["destroyed_at"] == refreshed.destroyed_at
        assert receipt["lifecycle"]["cancel"] is True
        assert receipt["lifecycle"]["confirmed"] is True
        assert receipt["lifecycle"]["destroy_error"] is None
        assert receipt["dossier"] == original_receipt["dossier"]
        assert receipt["verification"] == original_receipt["verification"]
        assert sum(e.type == "status" for e in ledger.list_events(job.job_id)) == 2
        assert reap_expired_from_ledger(settings=cfg, cli=cli) == []
        assert reap_terminal_checkpoints(cfg, cli) == [
            {"job_id": job.job_id, "checkpoint": checkpoint, "removed": True}
        ]
        assert checkpoints_removed == [checkpoint]
    finally:
        reset_ledger_for_tests()


def test_host_reaper_persists_cleanup_when_ledger_is_available(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)
    expires = "2026-01-01T00:00:00Z"
    name = "kh-host-expiry"

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        payload = ""
        if args[1] == "list":
            payload = json.dumps([{"name": name}])
        elif args[1] == "inspect":
            payload = json.dumps(
                {"labels": {"killhub.job_id": job.job_id, "killhub.expires_at": expires}}
            )
        return CliResult(tuple(args), 0, payload, "")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        ledger.append_sandbox_generation(
            job.job_id, environment_id=name, image="debian", expires_at=expires
        )
        result = reap_expired_from_host(
            settings=cfg, cli=MsbCli(cfg, runner=run), now=datetime(2026, 6, 1, tzinfo=timezone.utc)
        )
        assert result[0]["confirmed"] is True
        refreshed = ledger.get_job(job.job_id)
        assert refreshed.destroyed_at is not None
        assert refreshed.cleanup.status == "destroyed"
        assert ledger.get_receipt(job.job_id) is None
    finally:
        reset_ledger_for_tests()


def test_restart_recovery_preserves_evidence_and_publishes_verdict(tmp_path: Path) -> None:
    cfg = Settings(
        _env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}", ADMISSION_STORE="memory"
    )
    ledger = get_ledger(cfg)

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        assert list(args[1:]) == ["list", "--format", "json"]
        return CliResult(tuple(args), 0, "[]", "")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        gen = ledger.append_sandbox_generation(
            job.job_id, environment_id="kh-missing", image="debian", expires_at=job.expires_at
        )
        ledger.update_job_fields(job.job_id, status="installing", current_step="install")
        ledger.record_checkout_digest(
            job.job_id, gen.generation, before_install=True, digest="a" * 64
        )
        ledger.upsert_receipt(job.job_id, dossier={"previous_evidence": "recorded"})

        recover_interrupted_jobs(cfg, MsbCli(cfg, runner=run))
        receipt = ledger.get_receipt(job.job_id)
        assert ledger.get_job(job.job_id).status == "failed"
        assert receipt["lifecycle"]["confirmed"] is True
        assert receipt["dossier"]["previous_evidence"] == "recorded"
        verdict = receipt["dossier"]["detonation_verdict"]
        assert verdict["verdict"]["status"] == "ABORTED"
        assert verdict["target"]["package_sha256_before"] == "a" * 64
        assert verdict["target"]["package_sha256_after"] is None
    finally:
        reset_ledger_for_tests()


@pytest.mark.parametrize(
    ("ttl", "timeout", "expected"), [(120, 45, 45), (45, 120, 45), (45, 0, 45)]
)
def test_job_uses_shorter_absolute_lifetime(
    tmp_path: Path, ttl: int, timeout: int, expected: int
) -> None:
    cfg = Settings(
        _env_file=None,
        LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        ADMISSION_STORE="memory",
        PREFLIGHT_ENABLED=False,
        ENV_TTL_SECONDS=ttl,
        JOB_TIMEOUT_SECONDS=timeout,
    )
    try:
        job = create_job("https://github.com/example/fixture", settings=cfg)
        # Allow the two wall-clock reads to straddle one second.
        lifetime = datetime.fromisoformat(job.expires_at.replace("Z", "+00:00")) - (
            datetime.fromisoformat(job.created_at.replace("Z", "+00:00"))
        )
        assert expected <= lifetime.total_seconds() <= expected + 1
    finally:
        reset_ledger_for_tests()


def test_sandbox_create_refuses_expired_job_before_invoking_msb(tmp_path: Path) -> None:
    cfg = Settings(_env_file=None, LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}")
    ledger = get_ledger(cfg)

    def run(args: Sequence[str], timeout: float | None) -> CliResult:
        pytest.fail("An expired job must not reach the host CLI.")

    try:
        job = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=-60)
        with pytest.raises(HarnessError) as exc:
            create_environment(job.job_id, settings=cfg, cli=MsbCli(cfg, runner=run))
        assert exc.value.code == "job_expired"
        assert ledger.list_sandbox_generations(job.job_id) == []
    finally:
        reset_ledger_for_tests()


def test_claim_records_expiry_before_taking_a_worker_slot(tmp_path: Path) -> None:
    cfg = Settings(
        _env_file=None,
        LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        ADMISSION_STORE="memory",
        MSB_AUTO_CREATE=True,
    )
    ledger = get_ledger(cfg)
    try:
        expired = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=-60)
        waiting = ledger.create_job("https://github.com/example/fixture", env_ttl_seconds=60)

        claimed = claim_pending_job(settings=cfg)

        assert claimed is not None and claimed.job_id == waiting.job_id
        assert claimed.status == "analyzing"
        closed = ledger.get_job(expired.job_id)
        assert closed.status == "failed"
        assert closed.destroyed_at is None
        assert ledger.list_sandbox_generations(expired.job_id) == []
        receipt = ledger.get_receipt(expired.job_id)
        assert receipt["dossier"]["code"] == "job_expired"
        assert receipt["dossier"]["detonation_verdict"]["verdict"]["status"] == "ABORTED"
        statuses = [
            event.payload["status"]
            for event in ledger.list_events(expired.job_id)
            if event.type == "status"
        ]
        assert statuses == ["pending", "failed"]
        assert claim_pending_job(settings=cfg) is None
    finally:
        reset_ledger_for_tests()


def test_concurrent_workers_only_claim_a_pending_job_once(tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    with Ledger(db) as first, Ledger(db) as second:
        job = first.create_job("https://github.com/example/fixture", env_ttl_seconds=60)
        ready = Barrier(2)

        def attempt(ledger: Ledger) -> str | None:
            ready.wait(timeout=5)
            claimed = ledger.try_claim_pending_job(job.job_id)
            return claimed.job_id if claimed else None

        # Two connections exercise the database transaction across worker instances.
        with ThreadPoolExecutor(max_workers=2) as threads:
            results = list(threads.map(attempt, (first, second)))
        assert results.count(job.job_id) == 1
        assert results.count(None) == 1
        assert sum(event.message == "analyzing" for event in first.list_events(job.job_id)) == 1
