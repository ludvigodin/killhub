"""Install phase → deny-all remaining egress (D43, D63, D29, D65)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from config import get_settings
from errors import HarnessError
from harness import CliResult, ExecResult
from install import (
    InstallError,
    probe_control_plane_during_install,
    probe_offline_egress,
    provision_and_go_offline,
    run_install_commands,
    transition_to_verify_offline,
)
from jobs import get_ledger, reset_ledger_for_tests
from paths import validate_guest_path
from service import create_job

RUNTIME_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "webapp",
    "oci_image": "debian",
    "os_image": "linux",
    "runtime": "node",
    "workdir": "/tmp/killhub/repo",
    "source": {
        "type": "git",
        "url": "https://github.com/heroku/node-js-getting-started",
        "commit": "d33649d5edae61fc766fe6d47e530c475c05a7a0",
        "ref": "main",
    },
    "packages": [],
    "install_commands": [{"shell": "true", "timeout_seconds": 30}],
    "run_commands": [{"shell": "echo ready", "timeout_seconds": 30}],
    "services": [],
    "processes": [],
    "ports": [5000],
    "probes": [
        {
            "type": "http",
            "url": "http://127.0.0.1:5000/",
            "timeout_seconds": 5,
        }
    ],
    "summary": "test webapp profile for install unit tests",
    "verification_target": "original_application",
}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("screenshots.ensure_playwright_tooling", lambda *args, **kwargs: {})
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("DISCOVER_ON_CLAIM", "false")
    monkeypatch.setenv("INSTALL_ON_CLAIM", "false")
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    monkeypatch.setenv("PROFILE_STORAGE", str(tmp_path / "profiles"))
    monkeypatch.setenv("HELPERS_ROOT", str(tmp_path / "helpers"))
    monkeypatch.setenv("CONTROL_PLANE_DENY_HOSTS", "example.com")
    monkeypatch.setenv("CONTROL_PLANE_PROBE_URL", "https://example.com")
    monkeypatch.setenv("INSTALL_EGRESS_PROBE_URL", "https://github.com")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    (tmp_path / "helpers").mkdir(parents=True)
    for name in (
        "env_probe.sh",
        "network_probe.sh",
        "tooling_probe.sh",
        "mcp_stdio_verify.py",
        "screenshot_capture.py",
    ):
        (tmp_path / "helpers" / name).write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    get_settings.cache_clear()
    reset_ledger_for_tests()
    # provision_and_go_offline may call Playwright install for webapp intent (D63).
    monkeypatch.setattr(
        "screenshots.ensure_playwright_tooling",
        lambda *a, **k: {"status": "skipped", "reason": "unit_test"},
    )
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _seed_job_with_runtime() -> str:
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-install",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.append_profile_revision(
        job.job_id,
        phase="runtime",
        schema_version="1",
        profile=RUNTIME_PROFILE,
        storage_path=None,
    )
    return job.job_id


def test_guest_path_allows_opt_killhub() -> None:
    assert validate_guest_path("/opt/killhub/helpers/network_probe.sh").endswith("network_probe.sh")
    with pytest.raises(HarnessError):
        validate_guest_path("/usr/bin/wget")


def test_run_install_commands_flags_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        calls.append(joined)
        if "fail-me" in joined:
            return ExecResult("", "boom", 1)
        return ExecResult("ok", "", 0)

    monkeypatch.setattr("install.exec_command", _exec)
    profile = {
        **RUNTIME_PROFILE,
        "install_commands": [
            {"shell": "true"},
            {"shell": "fail-me"},
        ],
    }
    steps = run_install_commands(
        "env-install",
        profile,
        job_id=_seed_job_with_runtime(),
        settings=get_settings(),
    )
    assert steps[0].ok is True
    assert steps[1].ok is False
    assert "fail-me" in steps[1].name


def test_cp_probe_policy_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job_with_runtime()

    def _host_ok(url: str, *, timeout: float = 5.0) -> tuple[bool, str]:
        return True, "http_200"

    def _guest(
        environment_id: str,
        url: str,
        *,
        job_id: str,
        settings: Any,
        timeout: float = 5.0,
    ) -> tuple[str, int]:
        if "example.com" in url:
            return "denied", 1
        return "ok", 0

    monkeypatch.setattr("install._host_fetch_ok", _host_ok)
    monkeypatch.setattr("install._guest_fetch", _guest)
    evidence = probe_control_plane_during_install(
        "env-install", job_id=job_id, settings=get_settings()
    )
    assert evidence["classification"] == "policy_denied"


def test_cp_probe_bypass_raises_on_provision(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job_with_runtime()

    monkeypatch.setattr(
        "install.preinstall_assessment_tooling",
        lambda *a, **k: {"probe_exit": 0},
    )
    monkeypatch.setattr(
        "install.probe_control_plane_during_install",
        lambda *a, **k: {"classification": "policy_bypass"},
    )
    with pytest.raises(InstallError) as err:
        provision_and_go_offline(job_id, settings=get_settings())
    assert err.value.code == "cp_bypass"


def test_offline_probe_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job_with_runtime()
    monkeypatch.setattr(
        "install._guest_fetch",
        lambda *a, **k: ("denied", 1),
    )
    result = probe_offline_egress("env-install", job_id=job_id, settings=get_settings())
    assert result["classification"] == "policy_denied"


def test_transition_uses_snapshot_no_net(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job_with_runtime()
    cli = MagicMock()
    cli.snapshot_remove_group.return_value = CliResult((), 0, "", "")
    cli.snapshot_create.return_value = CliResult((), 0, "", "")
    cli.stop.return_value = CliResult((), 0, "", "")
    cli.remove.return_value = CliResult((), 0, "", "")
    cli.snapshot_restore_offline.return_value = CliResult((), 0, "", "")
    cli.run.return_value = CliResult((), 0, "", "")
    monkeypatch.setattr("install.wait_until_ready", lambda *a, **k: None)

    meta = transition_to_verify_offline(
        "env-install", job_id=job_id, settings=get_settings(), cli=cli
    )
    assert meta["phase"] == "verify"
    cli.snapshot_create.assert_called_once()
    assert cli.snapshot_create.call_args.kwargs.get("full") is True
    cli.snapshot_restore_offline.assert_called_once()
    assert cli.snapshot_restore_offline.call_args.kwargs["name"] == "env-install"


def test_provision_and_go_offline_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job_with_runtime()
    monkeypatch.setattr(
        "install.preinstall_assessment_tooling",
        lambda *a, **k: {"probe_exit": 0, "helpers_root": "/opt/killhub/helpers"},
    )
    monkeypatch.setattr(
        "install.probe_control_plane_during_install",
        lambda *a, **k: {"classification": "policy_denied"},
    )
    monkeypatch.setattr(
        "install.run_install_commands",
        lambda *a, **k: [
            type("S", (), {"name": "true", "ok": True, "detail": "", "exit_code": 0})()
        ],
    )
    monkeypatch.setattr(
        "install.transition_to_verify_offline",
        lambda *a, **k: {"snapshot_group": "g", "phase": "verify"},
    )
    monkeypatch.setattr(
        "install.probe_offline_egress",
        lambda *a, **k: {"classification": "policy_denied"},
    )

    result = provision_and_go_offline(job_id, settings=get_settings())
    assert result.network_phase == "verify"
    assert result.install_failures == []
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status == "verifying"
    assert job.status != "completed"
    events = get_ledger().list_events(job_id)
    kinds = [e.type for e in events]
    assert "status" in kinds
    assert "log" in kinds


def test_repair_retries_install_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_job_with_runtime()
    attempts = {"n": 0}

    def _install(*_a: Any, **_k: Any) -> list[Any]:
        attempts["n"] += 1
        ok = attempts["n"] >= 2
        return [
            type(
                "S",
                (),
                {
                    "name": "npm install",
                    "ok": ok,
                    "detail": "" if ok else "fail",
                    "exit_code": 0 if ok else 1,
                },
            )()
        ]

    monkeypatch.setattr(
        "install.preinstall_assessment_tooling",
        lambda *a, **k: {"probe_exit": 0},
    )
    monkeypatch.setattr(
        "screenshots.ensure_playwright_tooling",
        lambda *a, **k: {"status": "skipped"},
    )
    monkeypatch.setattr(
        "install.probe_control_plane_during_install",
        lambda *a, **k: {"classification": "policy_denied"},
    )
    monkeypatch.setattr("install.run_install_commands", _install)
    monkeypatch.setattr(
        "install.transition_to_verify_offline",
        lambda *a, **k: {"snapshot_group": "g", "phase": "verify"},
    )
    monkeypatch.setattr(
        "install.probe_offline_egress",
        lambda *a, **k: {"classification": "policy_denied"},
    )

    result = provision_and_go_offline(job_id, settings=get_settings())
    assert attempts["n"] == 2
    assert result.repair_attempts == 2
    assert result.install_failures == []
