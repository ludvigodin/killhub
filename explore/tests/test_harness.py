"""Harness unit tests — command construction + destroy confirm semantics (T0).

These do **not** substitute for a real `msb doctor` / create on VX1.
"""

from __future__ import annotations

from typing import Sequence

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
from reaper import reap_expired_from_host, reap_expired_from_ledger


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
