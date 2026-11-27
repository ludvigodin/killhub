"""Optional in-guest screenshots (D18, D31, D38)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from config import get_settings
from harness import ExecResult
from jobs import get_ledger, reset_ledger_for_tests
from screenshots import (
    capture_http_screenshot,
    maybe_capture_after_verify,
    redact_caption,
    should_capture_screenshots,
)
from service import create_job

WEBAPP_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "webapp",
    "oci_image": "debian",
    "workdir": "/tmp/killhub/repo",
    "source": {
        "type": "git",
        "url": "https://github.com/heroku/node-js-getting-started",
        "commit": "d33649d5edae61fc766fe6d47e530c475c05a7a0",
    },
    "ports": [5000],
    "probes": [
        {
            "name": "http-root",
            "type": "http",
            "url": "http://127.0.0.1:5000/",
            "accept": [200],
        }
    ],
    "verification_target": "original_application",
}

MCP_STDIO_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "git_mcp",
    "mcp": {"transport": "stdio", "command": {"argv": ["node", "index.js"]}},
    "ports": [],
    "probes": [],
    "verification_target": "original_application",
}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("SCREENSHOTS_ON_CLAIM", "false")
    monkeypatch.setenv("SCREENSHOT_STORAGE", str(tmp_path / "shots"))
    monkeypatch.setenv("MAX_SCREENSHOTS_PER_JOB", "3")
    monkeypatch.setenv("MAX_COPY_BYTES", "1000000")
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _seed_webapp(*, readiness_passed: bool = True) -> str:
    job = create_job("https://github.com/heroku/node-js-getting-started")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-shot",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.append_profile_revision(
        job.job_id,
        phase="runtime",
        schema_version="1",
        profile=WEBAPP_PROFILE,
    )
    ledger.update_job_fields(
        job.job_id,
        status="verifying",
        readiness={
            "passed": readiness_passed,
            "probe": "http-root",
            "detail": {"ok": readiness_passed, "type": "http"},
        },
        verification={"kind": "original_application"},
        progress=90,
    )
    return job.job_id


def test_redact_caption_strips_secret_shapes() -> None:
    text = "still api_key=supersecret CKEY_abcdef0123456789abcdef01 ok"
    out = redact_caption(text)
    assert "supersecret" not in out
    assert "CKEY_" not in out
    assert "[redacted]" in out


def test_skip_mcp_stdio_even_if_readiness_passed() -> None:
    job = create_job("https://github.com/modelcontextprotocol/servers")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-mcp",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.append_profile_revision(
        job.job_id,
        phase="runtime",
        schema_version="1",
        profile=MCP_STDIO_PROFILE,
    )
    ledger.update_job_fields(
        job.job_id,
        status="verifying",
        readiness={"passed": True, "probe": "mcp_handshake_stdio"},
        verification={"kind": "original_application"},
    )
    ok, reason = should_capture_screenshots(job.job_id, settings=get_settings())
    assert ok is False
    assert reason == "cli_only_mcp"


def test_skip_when_readiness_failed() -> None:
    job_id = _seed_webapp(readiness_passed=False)
    ok, reason = should_capture_screenshots(job_id, settings=get_settings())
    assert ok is False
    assert reason == "readiness_not_passed"


def test_capture_emits_screenshot_event(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job_id = _seed_webapp()
    png = tmp_path / "fake.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "screenshot_capture" in joined:
            return ExecResult("ok:/tmp/killhub/screenshots/x.png:72\n", "", 0)
        if "chromium" in joined:
            return ExecResult("/usr/bin/chromium\n", "", 0)
        return ExecResult("", "", 0)

    def _copy_out(environment_id, guest_src, artifact_kind, **kwargs):
        dest = Path(get_settings().screenshot_storage)
        if not dest.is_absolute():
            dest = Path(__file__).resolve().parent.parent.parent / dest
        # settings path already absolute via fixture env
        dest = Path(get_settings().screenshot_storage) / kwargs["job_id"]
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / (kwargs.get("filename") or "shot.png")
        out.write_bytes(png.read_bytes())
        return out

    monkeypatch.setattr("screenshots.exec_command", _exec)
    monkeypatch.setattr("screenshots.copy_out", _copy_out)

    result = capture_http_screenshot(job_id, settings=get_settings())
    assert result.status == "captured"
    assert len(result.screenshots) == 1
    events = get_ledger().list_events(job_id)
    assert any(e.type == "screenshot" for e in events)
    shots = get_ledger().list_screenshots(job_id)
    assert len(shots) == 1
    assert shots[0]["caption"]
    # Job must not be completed by capture.
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status != "completed"


def test_empty_timeline_ok_for_mcp_skip() -> None:
    job = create_job("https://github.com/modelcontextprotocol/servers")
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-mcp2",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.append_profile_revision(
        job.job_id,
        phase="runtime",
        schema_version="1",
        profile=MCP_STDIO_PROFILE,
    )
    ledger.update_job_fields(
        job.job_id,
        readiness={"passed": True, "probe": "mcp"},
        verification={"kind": "original_application"},
    )
    result = maybe_capture_after_verify(job.job_id, settings=get_settings())
    assert result.status == "skipped"
    assert get_ledger().list_screenshots(job.job_id) == []


def test_screenshot_cap_skips(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    job_id = _seed_webapp()
    ledger = get_ledger()
    shot_dir = Path(get_settings().screenshot_storage) / job_id
    shot_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        path = shot_dir / f"{i}.png"
        path.write_bytes(b"\x89PNG" + b"\x00" * 40)
        ledger.insert_screenshot(
            job_id,
            step="verify",
            caption=f"cap {i}",
            storage_path=str(path),
        )
    ok, reason = should_capture_screenshots(job_id, settings=get_settings())
    assert ok is False
    assert reason == "screenshot_cap"
    # Capture path must not call msb when capped.
    monkeypatch.setattr(
        "screenshots.exec_command",
        MagicMock(side_effect=AssertionError("should not exec")),
    )
    result = capture_http_screenshot(job_id, settings=get_settings())
    assert result.status == "skipped"
