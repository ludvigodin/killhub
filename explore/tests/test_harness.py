"""Harness unit tests — command construction + destroy confirm semantics (T0).

These do **not** substitute for a real `msb doctor` / create on VX1.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Sequence
from unittest.mock import MagicMock
from uuid import uuid4

from harness import (
    CliResult,
    DestroyResult,
    EnvironmentPlan,
    MsbCli,
    create_environment,
    destroy_environment,
    environment_name_for_job,
    normalize_memory,
    touch_if_before_expiry,
    wait_until_ready,
)
from jobs import get_ledger
from reaper import reap_expired_from_host, reap_expired_from_ledger, reap_terminal_checkpoints


def test_normalize_memory_and_env_name() -> None:
    assert normalize_memory("4Gi") == "4G"
    assert normalize_memory("512Mi") == "512M"
    assert normalize_memory("1G") == "1G"
    name = environment_name_for_job("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    assert name.startswith("kh-")
    assert " " not in name


def test_create_wait_destroy_lifecycle(client, auth_header, monkeypatch) -> None:
    _ = client, auth_header
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    monkeypatch.setenv("MSB_DEFAULT_MEMORY", "512M")
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    ledger = get_ledger(cfg)
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=3600,
    )
    # Keep the job off the worker claim queue — D83 fails claimed stubs when
    # pipeline flags are off (conftest default), which races this unit test.
    ledger.update_job_fields(
        job.job_id,
        status="analyzing",
        current_step="harness unit test",
    )

    calls: list[tuple[str, ...]] = []
    status_calls = {"n": 0}
    env_name = environment_name_for_job(job.job_id)

    def sequenced(argv: Sequence[str], timeout: float | None) -> CliResult:
        _ = timeout
        calls.append(tuple(argv))
        joined = " ".join(argv)
        if "create" in joined:
            return CliResult(tuple(argv), 0, "ok", "")
        if "stop" in joined:
            return CliResult(tuple(argv), 0, "stopped", "")
        if "remove" in joined:
            return CliResult(tuple(argv), 0, "removed", "")
        if "status" in joined:
            status_calls["n"] += 1
            if status_calls["n"] <= 2:
                return CliResult(tuple(argv), 0, f"{env_name} running", "")
            return CliResult(tuple(argv), 1, "", "not found")
        return CliResult(tuple(argv), 0, "", "")

    cli = MsbCli(cfg, runner=sequenced)

    gen = create_environment(
        job.job_id,
        EnvironmentPlan(image="debian", cpus=1, memory="512M"),
        settings=cfg,
        cli=cli,
    )
    assert gen.environment_id == env_name
    assert gen.expires_at == job.expires_at

    wait_until_ready(gen.environment_id, settings=cfg, cli=cli, timeout_seconds=5)

    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.sandbox_id == gen.environment_id
    assert refreshed.current_sandbox_generation == 1

    result = destroy_environment(
        gen.environment_id,
        job_id=job.job_id,
        reason="test",
        settings=cfg,
        cli=cli,
    )
    assert isinstance(result, DestroyResult)
    assert result.confirmed is True
    gens = ledger.list_sandbox_generations(job.job_id)
    assert gens[0].state == "destroyed"
    assert gens[0].destroyed_at is not None

    create_argv = next(c for c in calls if "create" in c)
    joined = " ".join(create_argv)
    assert "killhub.expires_at=" in joined
    assert "killhub.job_id=" in joined
    assert "--memory" in create_argv
    assert "512M" in create_argv
    assert "--net" in create_argv and "public" in create_argv
    assert "deny@host" in joined
    assert "deny@private" in joined
    assert "deny@meta" in joined
    assert "--env" in create_argv
    assert "KILLHUB_CANARY_TOKEN=" in joined

    # SSE/lifecycle must not include canary plaintext.
    for event in ledger.list_events(job.job_id):
        blob = f"{event.message}{event.payload}"
        assert "CKEY_" not in blob
        if "canaries" in event.payload:
            assert "fingerprints" in event.payload.get("canaries", event.payload)

    get_settings.cache_clear()


def test_touch_does_not_run_after_expiry(monkeypatch) -> None:
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        calls.append(tuple(argv))
        return CliResult(tuple(argv), 0, "", "")

    cli = MsbCli(cfg, runner=runner)
    touched = touch_if_before_expiry(
        "kh-demo",
        expires_at="2020-01-01T00:00:00Z",
        settings=cfg,
        cli=cli,
        now_iso="2026-01-01T00:00:00Z",
    )
    assert touched is False
    assert calls == []


def test_host_reaper_destroys_expired_label(monkeypatch) -> None:
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        joined = " ".join(argv)
        if "list" in joined:
            return CliResult(tuple(argv), 0, "expired-box\n", "")
        if "inspect" in joined:
            return CliResult(
                tuple(argv),
                0,
                "killhub.managed=1 killhub.expires_at=2020-01-01T00:00:00Z\n",
                "",
            )
        if "stop" in joined or "remove" in joined:
            return CliResult(tuple(argv), 0, "ok", "")
        if "status" in joined:
            return CliResult(tuple(argv), 1, "", "not found")
        return CliResult(tuple(argv), 0, "", "")

    cli = MsbCli(cfg, runner=runner)
    actions = reap_expired_from_host(settings=cfg, cli=cli)
    assert any(a["environment_id"] == "expired-box" and a["confirmed"] for a in actions)


def test_ledger_reaper_marks_expired(client, auth_header, monkeypatch) -> None:
    _ = auth_header
    from datetime import datetime, timedelta, timezone

    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()
    ledger = get_ledger(cfg)
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=1,
    )
    past = (
        (datetime.now(timezone.utc) - timedelta(hours=1))
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    # Force expires_at in the past via generation + job field update.
    ledger.update_job_fields(job.job_id, expires_at=past)
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="kh-expired",
        image="debian",
        expires_at=past,
        state="running",
        cpus=1,
        memory="512M",
    )

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        joined = " ".join(argv)
        if "list" in joined:
            return CliResult(tuple(argv), 0, "kh-expired\n", "")
        if "stop" in joined or "remove" in joined:
            return CliResult(tuple(argv), 0, "ok", "")
        if "status" in joined:
            return CliResult(tuple(argv), 1, "", "not found")
        return CliResult(tuple(argv), 0, "", "")

    cli = MsbCli(cfg, runner=runner)
    actions = reap_expired_from_ledger(
        settings=cfg,
        cli=cli,
        now=datetime.now(timezone.utc),
    )
    assert any(a["environment_id"] == "kh-expired" and a["confirmed"] for a in actions)
    gens = ledger.list_sandbox_generations(job.job_id)
    assert gens[0].state == "destroyed"
    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.destroyed_at is not None
    get_settings.cache_clear()


def test_reaper_prunes_only_confirmed_terminal_checkpoint(monkeypatch):
    ids = [uuid4() for _ in range(5)]
    groups = [f"kh-snap-{i.hex}" for i in ids]
    cli = MagicMock()
    cli.run.side_effect = [
        SimpleNamespace(stdout=json.dumps([{"name": n} for n in [*groups, "operator-backup"]])),
        SimpleNamespace(stdout=json.dumps([{"name": f"kh-{ids[1]}"}])),
    ]
    cli.snapshot_remove_group.return_value.ok = True
    jobs = {str(i): SimpleNamespace(status="completed", destroyed_at="confirmed") for i in ids[:4]}
    jobs[str(ids[2])].status = "installing"
    ledger = MagicMock()
    ledger.get_job.side_effect = jobs.get
    ledger.get_receipt.side_effect = lambda i: {"lifecycle": {"confirmed": i != str(ids[3])}}
    monkeypatch.setattr("reaper.get_ledger", lambda cfg: ledger)
    actions = reap_terminal_checkpoints(MagicMock(), cli)
    assert actions == [{"job_id": str(ids[0]), "checkpoint": groups[0], "removed": True}]
    cli.snapshot_remove_group.assert_called_once_with(groups[0])


def test_restart_recovers_only_absent_generation(tmp_path, monkeypatch):
    import pytest

    from config import Settings
    from ledger import Ledger
    from reaper import recover_interrupted_jobs

    cfg = Settings(LEDGER_URL=f"sqlite:///{tmp_path}/ledger.db")
    with Ledger.from_url(cfg.ledger_url) as ledger:
        monkeypatch.setattr("reaper.get_ledger", lambda _: ledger)
        cli = MagicMock()
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=120)
        ledger.append_sandbox_generation(
            job.job_id,
            environment_id="kh-test",
            image="debian",
            expires_at=job.expires_at,
            state="running",
            cpus=1,
            memory="512M",
        )
        ledger.update_job_fields(job.job_id, status="installing", current_step="install phase")
        cli.run.return_value.stdout = '{"error":"inventory unavailable"}'
        with pytest.raises(ValueError):
            recover_interrupted_jobs(cfg, cli)
        cli.run.return_value.stdout = '[{"name":"kh-test"}]'
        recover_interrupted_jobs(cfg, cli)
        assert ledger.get_job(job.job_id).status == "installing"
        cli.run.return_value.stdout = "[]"
        recover_interrupted_jobs(cfg, cli)
        recovered = ledger.get_job(job.job_id)
        assert recovered.status == "failed"
        assert recovered.cleanup.status == "destroyed"
        assert ledger.list_sandbox_generations(job.job_id)[0].destroyed_at == recovered.destroyed_at
        assert ledger.get_receipt(job.job_id)["dossier"]["code"] == "worker_restart"
        recover_interrupted_jobs(cfg, cli)
        assert ledger.get_job(job.job_id).event_cursor == recovered.event_cursor


def test_restart_removes_leftover_live_sandbox_then_finalizes(tmp_path, monkeypatch):
    from config import Settings
    from ledger import Ledger
    from reaper import recover_interrupted_jobs

    cfg = Settings(LEDGER_URL=f"sqlite:///{tmp_path}/ledger.db")
    with Ledger.from_url(cfg.ledger_url) as ledger:
        monkeypatch.setattr("reaper.get_ledger", lambda _: ledger)
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=120)
        ledger.append_sandbox_generation(
            job.job_id,
            environment_id="kh-left",
            image="debian",
            expires_at=job.expires_at,
            state="running",
            cpus=1,
            memory="512M",
        )
        ledger.update_job_fields(job.job_id, status="verifying", current_step="verify")
        cli = MagicMock()
        inventories = iter(['[{"name":"kh-left"}]', "[]"])
        cli.run.side_effect = lambda *a, **k: MagicMock(stdout=next(inventories))

        recover_interrupted_jobs(cfg, cli)

        cli.remove.assert_called_once_with("kh-left", force=True)
        recovered = ledger.get_job(job.job_id)
        assert recovered.status == "failed"
        assert recovered.error == "Worker restarted; its leftover sandbox was removed."
        assert recovered.cleanup.status == "destroyed"


def test_restart_fails_in_flight_job_that_never_created_a_sandbox(tmp_path, monkeypatch):
    from config import Settings
    from ledger import Ledger
    from reaper import recover_interrupted_jobs

    cfg = Settings(LEDGER_URL=f"sqlite:///{tmp_path}/ledger.db")
    with Ledger.from_url(cfg.ledger_url) as ledger:
        monkeypatch.setattr("reaper.get_ledger", lambda _: ledger)
        job = ledger.create_job("https://github.com/example/demo", env_ttl_seconds=120)
        ledger.update_job_fields(job.job_id, status="analyzing", current_step="preflight")
        cli = MagicMock()

        recover_interrupted_jobs(cfg, cli)

        cli.run.assert_not_called()  # no inventory needed when no VM was recorded
        recovered = ledger.get_job(job.job_id)
        assert recovered.status == "failed"
        assert recovered.destroyed_at is None  # no VM existed: no destroy claim (D57)
        receipt = ledger.get_receipt(job.job_id)
        assert receipt["dossier"]["code"] == "worker_restart"
        assert receipt["verification"]["kind"] == "setup_failed"
        assert not ledger.finalize_interrupted_before_sandbox(recovered)  # idempotent
