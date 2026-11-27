"""T1 exec + D60 copy path policy tests."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from errors import HarnessError
from harness import CliResult, MsbCli, copy_in, exec_command
from paths import (
    guest_env_has_forbidden_keys,
    resolve_copy_in_source,
    resolve_copy_out_dest,
    validate_guest_path,
)


def test_copy_in_rejects_absolute_and_traversal(tmp_path: Path, monkeypatch) -> None:
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "env_probe.sh").write_text("#!/bin/sh\necho ok\n")
    monkeypatch.setenv("HELPERS_ROOT", str(helpers))
    from config import get_settings

    get_settings.cache_clear()

    with pytest.raises(HarnessError) as abs_err:
        resolve_copy_in_source("/etc/passwd")
    assert abs_err.value.code == "path_forbidden"

    with pytest.raises(HarnessError):
        resolve_copy_in_source("../secrets.txt")

    with pytest.raises(HarnessError):
        resolve_copy_in_source("nested/../../etc/passwd")

    ok = resolve_copy_in_source("env_probe")
    assert ok.name == "env_probe.sh"
    get_settings.cache_clear()


def test_guest_and_artifact_path_rules(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACT_STORAGE", str(tmp_path / "artifacts"))
    monkeypatch.setenv("SCREENSHOT_STORAGE", str(tmp_path / "shots"))
    from config import get_settings

    get_settings.cache_clear()

    assert validate_guest_path("/tmp/killhub/a.txt").endswith("a.txt")
    with pytest.raises(HarnessError):
        validate_guest_path("/etc/passwd")
    with pytest.raises(HarnessError):
        validate_guest_path("/tmp/killhub/../etc/passwd")

    dest = resolve_copy_out_dest(
        "job-1",
        "lockfile",
        filename="package-lock.json",
    )
    assert dest.name == "package-lock.json"
    assert "artifacts" in str(dest)
    with pytest.raises(HarnessError):
        resolve_copy_out_dest("job-1", "nope", filename="x")
    get_settings.cache_clear()


def test_forbidden_env_detection() -> None:
    text = "PATH=/bin\nVULTR_API_KEY=secret\nHOME=/root\n"
    assert "VULTR_API_KEY" in guest_env_has_forbidden_keys(text)
    assert guest_env_has_forbidden_keys("PATH=/bin\nHOME=/root\n") == []


def test_exec_logs_nonzero_exit(client, auth_header, monkeypatch) -> None:
    _ = auth_header
    from config import get_settings
    from jobs import get_ledger

    get_settings.cache_clear()
    cfg = get_settings()
    ledger = get_ledger(cfg)
    job = ledger.create_job(
        "https://github.com/heroku/node-js-getting-started",
        env_ttl_seconds=600,
    )

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        _ = timeout
        return CliResult(tuple(argv), 7, "", "boom")

    cli = MsbCli(cfg, runner=runner)
    result = exec_command(
        "kh-demo",
        ["false"],
        job_id=job.job_id,
        settings=cfg,
        cli=cli,
    )
    assert result.exit_code == 7
    events = ledger.list_events(job.job_id)
    assert any(e.type == "log" and "exec exit 7" in e.message for e in events)
    get_settings.cache_clear()


def test_copy_in_rejects_before_msb(client, auth_header, monkeypatch) -> None:
    _ = client, auth_header
    from config import get_settings

    get_settings.cache_clear()
    cfg = get_settings()

    def runner(argv: Sequence[str], timeout: float | None) -> CliResult:
        raise AssertionError(f"msb should not be called for forbidden path: {argv}")

    cli = MsbCli(cfg, runner=runner)
    with pytest.raises(HarnessError) as err:
        copy_in(
            "kh-demo",
            "/etc/passwd",
            "/tmp/killhub/x",
            job_id=None,
            settings=cfg,
            cli=cli,
        )
    assert err.value.code == "path_forbidden"
    get_settings.cache_clear()
