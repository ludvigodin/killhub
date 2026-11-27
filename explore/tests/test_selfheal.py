"""D80: lost-sandbox self-heal + reaper in-flight orphan guard (no real msb)."""

from __future__ import annotations

import json
from typing import Sequence

import pytest

from config import get_settings
from errors import HarnessError
from harness import LABEL_JOB, CliResult, MsbCli
from jobs import get_ledger
from reaper import reap_expired_from_ledger
from selfheal import heal_lost_sandbox, sandbox_alive

URL = "https://github.com/heroku/node-js-getting-started"


@pytest.fixture
def cfg(client):
    _ = client
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def _runner(*, live: str = "", labels: dict | None = None, status_err: str = "", calls=None):
    def run(argv: Sequence[str], timeout: float | None) -> CliResult:
        _ = timeout
        if calls is not None:
            calls.append(tuple(argv))
        cmd = argv[1] if len(argv) > 1 else ""
        if cmd == "list":
            return CliResult(tuple(argv), 0, live, "")
        if cmd == "inspect":
            return CliResult(tuple(argv), 0, json.dumps({"labels": labels or {}}), "")
        if cmd == "status":
            if status_err:
                return CliResult(tuple(argv), 1, "", status_err)
            return CliResult(tuple(argv), 0, "running", "")
        return CliResult(tuple(argv), 0, "ok", "")

    return run


def _job_with_sandbox(cfg, env_id: str = "kh-lost"):
    ledger = get_ledger(cfg)
    job = ledger.create_job(URL, env_ttl_seconds=3600)
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id=env_id,
        image="debian",
        expires_at=job.expires_at,
        state="running",
        cpus=1,
        memory="512M",
    )
    ledger.update_job_fields(job.job_id, status="installing")
    return ledger, ledger.get_job(job.job_id)


def test_sandbox_alive_classifies_msb_status(cfg) -> None:
    assert sandbox_alive("x", cli=MsbCli(cfg, runner=_runner())) is True
    gone = MsbCli(cfg, runner=_runner(status_err="error: sandbox not found: x"))
    assert sandbox_alive("x", cli=gone) is False
    weird = MsbCli(cfg, runner=_runner(status_err="error: daemon unavailable"))
    assert sandbox_alive("x", cli=weird) is None


def test_heal_lost_sandbox_resets_for_fresh_generation(cfg) -> None:
    ledger, job = _job_with_sandbox(cfg)
    calls: list = []
    cli = MsbCli(cfg, runner=_runner(status_err="error: sandbox not found: kh-lost", calls=calls))

    assert heal_lost_sandbox(job.job_id, cause="exec failed", attempt=1, settings=cfg, cli=cli)

    healed = ledger.get_job(job.job_id)
    assert healed.sandbox_id is None
    assert healed.status == "repairing"
    assert ledger.list_sandbox_generations(job.job_id)[0].state == "failed"
    assert any(c[1] == "remove" for c in calls)
    lost = [e for e in ledger.list_events(job.job_id) if e.message == "sandbox lost"]
    assert lost and lost[0].payload["environment_id"] == "kh-lost"


def test_heal_refuses_when_sandbox_still_alive(cfg) -> None:
    ledger, job = _job_with_sandbox(cfg)
    cli = MsbCli(cfg, runner=_runner())
    assert not heal_lost_sandbox(job.job_id, cause="apt failed", attempt=1, settings=cfg, cli=cli)
    assert ledger.get_job(job.job_id).sandbox_id == "kh-lost"


def test_heal_treats_shutdown_in_progress_as_lost(cfg) -> None:
    _, job = _job_with_sandbox(cfg)
    cli = MsbCli(cfg, runner=_runner())  # status still says running
    cause = "cannot prepare 'kh-lost': shutdown is already in progress"
    assert heal_lost_sandbox(job.job_id, cause=cause, attempt=1, settings=cfg, cli=cli)


def test_heal_refuses_after_cancel(cfg) -> None:
    ledger, job = _job_with_sandbox(cfg)
    ledger.update_job_fields(job.job_id, cancel_requested_at="2026-11-27T13:00:00Z")
    cli = MsbCli(cfg, runner=_runner(status_err="sandbox not found"))
    assert not heal_lost_sandbox(job.job_id, cause="x", attempt=1, settings=cfg, cli=cli)


def test_reaper_skips_orphan_of_in_flight_job(cfg) -> None:
    ledger = get_ledger(cfg)
    job = ledger.create_job(URL, env_ttl_seconds=3600)  # pending, no generation yet
    calls: list = []
    cli = MsbCli(
        cfg,
        runner=_runner(
            live="kh-new\n",
            labels={"killhub.managed": "1", LABEL_JOB: job.job_id},
            calls=calls,
        ),
    )
    actions = reap_expired_from_ledger(settings=cfg, cli=cli)
    assert actions == []
    assert not any(c[1] in {"stop", "remove"} for c in calls)


def test_reaper_still_destroys_orphan_of_unknown_job(cfg) -> None:
    cli = MsbCli(
        cfg,
        runner=_runner(
            live="kh-ghost\n",
            labels={"killhub.managed": "1", LABEL_JOB: "no-such-job"},
            status_err="not found",
        ),
    )
    actions = reap_expired_from_ledger(settings=cfg, cli=cli)
    assert [a["reason"] for a in actions] == ["orphan"]


def test_worker_heals_once_then_succeeds(cfg, monkeypatch) -> None:
    import worker

    monkeypatch.setattr(cfg, "discover_on_claim", True, raising=False)
    runs = {"n": 0}

    def flaky(job_id, settings, *, pipeline):
        runs["n"] += 1
        if runs["n"] == 1:
            raise HarnessError("sandbox not found", code="msb_failed")

    healed: list = []
    monkeypatch.setattr(worker, "_run_pipeline_once", flaky)
    monkeypatch.setattr(
        "selfheal.heal_lost_sandbox",
        lambda job_id, **kw: healed.append(kw["attempt"]) or True,
    )
    failed: list = []
    monkeypatch.setattr(worker, "_fail_claimed_job", lambda *a, **k: failed.append(a))

    worker._run_claimed_job("job-1", cfg)
    assert runs["n"] == 2 and healed == [1] and failed == []


def test_worker_fails_when_heal_budget_exhausted(cfg, monkeypatch) -> None:
    import worker

    monkeypatch.setattr(cfg, "discover_on_claim", True, raising=False)
    monkeypatch.setattr(cfg, "max_sandbox_heals", 1, raising=False)

    def always_lost(job_id, settings, *, pipeline):
        raise HarnessError("sandbox not found", code="msb_failed")

    monkeypatch.setattr(worker, "_run_pipeline_once", always_lost)
    monkeypatch.setattr("selfheal.heal_lost_sandbox", lambda job_id, **kw: True)
    failed: list = []
    monkeypatch.setattr(worker, "_fail_claimed_job", lambda *a, **k: failed.append(a))

    worker._run_claimed_job("job-1", cfg)
    assert len(failed) == 1
