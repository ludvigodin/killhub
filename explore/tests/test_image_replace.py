"""Same-job image replace (D36, D64)."""

from __future__ import annotations

from typing import Any, Sequence

import pytest

from config import get_settings
from discover import discover_runtime_profile
from errors import HarnessError
from fixtures import require_fixture
from harness import (
    CliResult,
    ExecResult,
    MsbCli,
    default_bootstrap_plan,
    images_differ,
    normalize_oci_image,
    plan_for_image,
    replace_environment,
)
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    monkeypatch.setenv("PROFILE_STORAGE", str(tmp_path / "profiles"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def test_normalize_and_differ() -> None:
    assert normalize_oci_image("Debian:latest") == "debian"
    assert not images_differ("debian", "debian:latest")
    assert images_differ("debian", "alpine")


def test_same_image_discover_skips_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    web = require_fixture("webapp_success")
    assert web["oci_image"] == "debian"

    class FakeExec:
        def __call__(self, environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "command -v git" in joined:
                return ExecResult("/usr/bin/git\n", "", 0)
            if "git rev-parse HEAD" in joined:
                return ExecResult(f"{web['commit']}\n", "", 0)
            if "---TREE---" in joined or "find ." in joined:
                return ExecResult(
                    '---PACKAGE_JSON---\n{"dependencies":{"express":"1"}}\n',
                    "",
                    0,
                )
            return ExecResult("", "", 0)

    replaced_calls: list[str] = []

    def _boom(*_a: Any, **_k: Any) -> None:
        replaced_calls.append("called")
        raise AssertionError("replace must not run on same image")

    monkeypatch.setattr(
        "discover.create_environment",
        lambda *a, **k: type(
            "G",
            (),
            {
                "environment_id": "env-same",
                "generation": 1,
                "state": "running",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )(),
    )
    monkeypatch.setattr("discover.wait_until_ready", lambda *a, **k: None)
    monkeypatch.setattr("discover.replace_environment", _boom)
    monkeypatch.setattr("discover.destroy_job_environment", lambda *a, **k: None)

    job = create_job(web["github_url"])
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-same",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    result = discover_runtime_profile(
        job.job_id, exec_fn=FakeExec(), create=True, destroy_on_failure=False
    )
    assert result.replaced is False
    assert result.profile["oci_image"] == "debian"
    assert replaced_calls == []
    events = ledger.list_events(job.job_id)
    assert any(
        e.type == "log"
        and e.payload.get("kind") == "sandbox_replace"
        and e.payload.get("skipped") is True
        for e in events
    )


def test_image_replace_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from harness import environment_name_for_job

    cfg = get_settings()
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger(cfg)
    commit = "a" * 40
    ledger.update_job_fields(job.job_id, resolved_commit=commit, status="planning")
    expected_name = environment_name_for_job(job.job_id)
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id=expected_name,
        image="debian",
        expires_at=job.expires_at,
        state="running",
        cpus=1,
        memory="512M",
    )
    job = ledger.get_job(job.job_id)
    assert job is not None
    expires = job.expires_at

    live: set[str] = {expected_name}
    creates: list[str] = []
    reclones: list[str] = []

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        joined = " ".join(argv)
        if "list" in joined:
            body = "\n".join(sorted(live)) + ("\n" if live else "")
            return CliResult(tuple(argv), 0, body, "")
        if "stop" in joined or "remove" in joined:
            live.discard(expected_name)
            return CliResult(tuple(argv), 0, "ok", "")
        if "status" in joined:
            target = argv[-1]
            if target in live:
                return CliResult(tuple(argv), 0, "running\n", "")
            return CliResult(tuple(argv), 1, "", "not found")
        return CliResult(tuple(argv), 0, "", "")

    cli = MsbCli(cfg, runner=runner)

    def fake_create(job_id: str, plan=None, *, settings=None, cli=None):
        assert plan is not None
        creates.append(plan.image)
        live.clear()
        live.add(expected_name)
        return ledger.append_sandbox_generation(
            job_id,
            environment_id=expected_name,
            image=plan.image,
            expires_at=expires,
            state="running",
            cpus=1,
            memory="512M",
        )

    def fake_clone(environment_id: str, **kwargs: Any) -> str:
        reclones.append(str(kwargs.get("commit") or ""))
        return str(kwargs.get("commit") or "")

    import harness as harness_mod

    monkeypatch.setattr(harness_mod, "create_environment", fake_create)
    monkeypatch.setattr(harness_mod, "wait_until_ready", lambda *a, **k: None)
    monkeypatch.setattr("discover.clone_and_resolve_commit", fake_clone)

    gen = replace_environment(
        job.job_id,
        plan_for_image("alpine", settings=cfg),
        settings=cfg,
        cli=cli,
        reclone=True,
    )
    assert gen.image == "alpine"
    assert gen.expires_at == expires
    assert gen.generation == 2
    assert reclones == [commit]
    assert creates == ["alpine"]

    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.destroyed_at is None
    assert refreshed.sandbox_id == expected_name
    assert refreshed.current_sandbox_generation == 2
    gens = ledger.list_sandbox_generations(job.job_id)
    assert gens[0].state == "replaced"
    assert gens[0].destroyed_at is not None
    assert gens[1].state == "running"

    events = ledger.list_events(job.job_id)
    replace_logs = [e for e in events if e.payload.get("kind") == "sandbox_replace"]
    assert any(e.payload.get("phase") == "start" for e in replace_logs)
    assert any(e.payload.get("phase") == "done" for e in replace_logs)


def test_same_image_replace_rejected() -> None:
    cfg = get_settings()
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger(cfg)
    from harness import environment_name_for_job

    name = environment_name_for_job(job.job_id)
    ledger.update_job_fields(job.job_id, resolved_commit="b" * 40)
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id=name,
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        if "list" in " ".join(argv):
            return CliResult(tuple(argv), 0, f"{name}\n", "")
        return CliResult(tuple(argv), 0, "", "")

    cli = MsbCli(cfg, runner=runner)
    with pytest.raises(HarnessError) as err:
        replace_environment(
            job.job_id,
            default_bootstrap_plan(cfg),
            settings=cfg,
            cli=cli,
            reclone=False,
        )
    assert err.value.code == "same_image"


def test_image_replace_fixture_triggers_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    fx = require_fixture("webapp_image_replace")
    assert fx["oci_image"] == "alpine"

    class FakeExec:
        def __call__(self, environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "command -v git" in joined:
                return ExecResult("/usr/bin/git\n", "", 0)
            if "git rev-parse HEAD" in joined:
                return ExecResult(f"{fx['commit']}\n", "", 0)
            if "---TREE---" in joined or "find ." in joined:
                return ExecResult(
                    '---PACKAGE_JSON---\n{"dependencies":{"express":"1"}}\n',
                    "",
                    0,
                )
            return ExecResult("", "", 0)

    replace_calls: list[str] = []

    def fake_replace(job_id: str, plan, **kwargs: Any):
        replace_calls.append(plan.image)
        ledger = get_ledger()
        job = ledger.get_job(job_id)
        assert job is not None
        return ledger.append_sandbox_generation(
            job_id,
            environment_id="env-alpine",
            image=plan.image,
            expires_at=job.expires_at,
            state="running",
        )

    monkeypatch.setattr(
        "discover.create_environment",
        lambda *a, **k: type(
            "G",
            (),
            {
                "environment_id": "env-boot",
                "generation": 1,
                "state": "running",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )(),
    )
    monkeypatch.setattr("discover.wait_until_ready", lambda *a, **k: None)
    monkeypatch.setattr("discover.replace_environment", fake_replace)
    monkeypatch.setattr("discover.destroy_job_environment", lambda *a, **k: None)
    # Same public URL as webapp_success; force the replace-only fixture by id.
    monkeypatch.setattr("discover.match_fixture", lambda _url: fx)

    job = create_job(fx["github_url"])
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-boot",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    result = discover_runtime_profile(
        job.job_id, exec_fn=FakeExec(), create=True, destroy_on_failure=False
    )
    assert result.replaced is True
    assert result.profile["oci_image"] == "alpine"
    assert replace_calls == ["alpine"]
