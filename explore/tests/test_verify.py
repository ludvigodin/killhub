"""Readiness verify + verification kinds (D30, D37, D54, D62)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from config import get_settings
from fixtures import require_fixture
from harness import ExecResult
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job
from verify import (
    VerifyError,
    assert_built_checkout_launch,
    verify_readiness,
)

WEBAPP_PROFILE: dict[str, Any] = {
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
    "packages": ["nodejs", "npm"],
    "install_commands": [
        {"argv": ["npm", "install"], "cwd": "/tmp/killhub/repo", "timeout_seconds": 600}
    ],
    "run_commands": [{"argv": ["npm", "start"], "cwd": "/tmp/killhub/repo", "timeout_seconds": 60}],
    "services": [],
    "processes": [
        {
            "name": "web",
            "command": {
                "argv": ["npm", "start"],
                "cwd": "/tmp/killhub/repo",
                "timeout_seconds": 3600,
            },
            "supervise": "restart",
            "ready_after_seconds": 0,
        }
    ],
    "ports": [5000],
    "probes": [
        {
            "name": "http-root",
            "type": "http",
            "url": "http://127.0.0.1:5000/",
            "accept": [200],
            "timeout_seconds": 5,
        }
    ],
    "summary": "test webapp",
    "verification_target": "original_application",
}

MCP_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "git_mcp",
    "oci_image": "debian",
    "os_image": "linux",
    "runtime": "node",
    "workdir": "/tmp/killhub/repo/src/filesystem",
    "source": {
        "type": "git",
        "url": "https://github.com/modelcontextprotocol/servers",
        "commit": "b502fd9fc711de7285977396db3b8a732d1c9f64",
        "ref": "v2.6.0",
    },
    "packages": ["nodejs", "npm"],
    "install_commands": [
        {
            "argv": ["npm", "install"],
            "cwd": "/tmp/killhub/repo/src/filesystem",
            "timeout_seconds": 600,
        }
    ],
    "run_commands": [
        {
            "argv": ["node", "dist/index.js", "/tmp/killhub/repo"],
            "cwd": "/tmp/killhub/repo/src/filesystem",
            "timeout_seconds": 60,
        }
    ],
    "services": [],
    "processes": [],
    "ports": [],
    "summary": "MCP filesystem",
    "verification_target": "original_application",
    "mcp": {
        "transport": "stdio",
        "launch_command": {
            "argv": ["node", "dist/index.js", "/tmp/killhub/repo"],
            "cwd": "/tmp/killhub/repo/src/filesystem",
            "timeout_seconds": 30,
        },
        "readiness": {
            "type": "mcp_handshake",
            "transport": "stdio",
            "timeout_seconds": 30,
        },
    },
}


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("VERIFY_ON_CLAIM", "false")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    monkeypatch.setenv("PROFILE_STORAGE", str(tmp_path / "profiles"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _seed(url: str, profile: dict[str, Any], *, commit: str) -> str:
    job = create_job(url)
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-verify",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.update_job_fields(job.job_id, resolved_commit=commit)
    ledger.append_profile_revision(
        job.job_id,
        phase="runtime",
        schema_version="1",
        profile=profile,
        storage_path=None,
    )
    return job.job_id


def test_fixture_pins_match_profiles() -> None:
    web = require_fixture("webapp_success")
    mcp = require_fixture("git_mcp_filesystem")
    assert web["commit"] == WEBAPP_PROFILE["source"]["commit"]
    assert mcp["commit"] == MCP_PROFILE["source"]["commit"]
    assert mcp["mcp"]["transport"] == "stdio"


def test_rejects_npx_y_for_original_application() -> None:
    profile = {
        **WEBAPP_PROFILE,
        "run_commands": [
            {
                "argv": ["npx", "-y", "some-pkg"],
                "cwd": "/tmp/killhub/repo",
                "timeout_seconds": 30,
            }
        ],
    }
    with pytest.raises(VerifyError) as err:
        assert_built_checkout_launch(profile, resolved_commit=profile["source"]["commit"])
    assert err.value.code == "unpinned_registry_launch"


def test_webapp_http_readiness_sets_kind_not_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed(
        WEBAPP_PROFILE["source"]["url"],
        WEBAPP_PROFILE,
        commit=WEBAPP_PROFILE["source"]["commit"],
    )

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "nohup" in joined:
            return ExecResult("1234\n", "", 0)
        if "http_code" in joined or "wget" in joined or "curl" in joined:
            return ExecResult("http_code:200\n", "", 0)
        if "sleep" in joined:
            return ExecResult("", "", 0)
        return ExecResult("", "", 0)

    monkeypatch.setattr("verify.exec_command", _exec)
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is True
    assert result.verification_kind == "original_application"
    assert result.completed is False
    assert result.destroyed is False
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status == "verifying"
    assert job.status != "completed"
    assert job.readiness and job.readiness["passed"] is True
    assert job.verification == {"kind": "original_application"}
    assert job.destroyed_at is None


def test_mcp_stdio_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed(
        MCP_PROFILE["source"]["url"],
        MCP_PROFILE,
        commit=MCP_PROFILE["source"]["commit"],
    )
    evidence = {
        "ok": True,
        "tool_count": 2,
        "tool_names": ["read_file", "list_directory"],
        "protocol": "2024-11-05",
    }

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "mcp_stdio_verify" in joined:
            return ExecResult(json.dumps(evidence) + "\n", "", 0)
        return ExecResult("", "", 0)

    monkeypatch.setattr("verify.exec_command", _exec)
    monkeypatch.setattr("verify.copy_in", lambda *a, **k: None)
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is True
    assert result.verification_kind == "original_application"
    assert result.verify_result.get("evidence", {}).get("tool_count") == 2
    job = get_ledger().get_job(job_id)
    assert job is not None
    assert job.status == "verifying"
    assert job.destroyed_at is None


def test_generated_demo_keeps_original_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    profile = {
        **WEBAPP_PROFILE,
        "intent": "demo",
        "verification_target": "generated_demo",
        "original_failure": {
            "step": "discover",
            "summary": "no webapp fit",
        },
        "probes": [
            {
                "name": "http-root",
                "type": "http",
                "url": "http://127.0.0.1:8000/",
                "accept": [200],
                "timeout_seconds": 5,
            }
        ],
        "processes": [
            {
                "name": "demo",
                "command": {
                    "shell": "python3 -m http.server 8000",
                    "cwd": "/tmp/killhub/repo",
                    "timeout_seconds": 60,
                },
                "supervise": "restart",
                "ready_after_seconds": 0,
            }
        ],
    }
    job_id = _seed(profile["source"]["url"], profile, commit=profile["source"]["commit"])

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "http_code" in joined or "wget" in joined or "curl" in joined:
            return ExecResult("http_code:200\n", "", 0)
        return ExecResult("1\n", "", 0)

    monkeypatch.setattr("verify.exec_command", _exec)
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is True
    assert result.verification_kind == "generated_demo"
    assert result.verification is not None
    assert result.verification["original_failure"]["summary"] == "no webapp fit"


def test_setup_failed_short_circuit_no_demo() -> None:
    fail = require_fixture("setup_failed")
    job = create_job(fail["github_url"])
    ledger = get_ledger()
    # Sandbox stays alive for setup_failed evidence (plan 14); mark terminal after.
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-fail",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    verification = {
        "kind": "setup_failed",
        "original_failure": {"step": "discover", "summary": "forbid_demo"},
    }
    ledger.finalize_job(
        job.job_id,
        status="failed",
        receipt={"verification": verification},
        verification=verification,
        readiness={"passed": False, "probe": "none", "detail": {}, "at": "t"},
    )
    result = verify_readiness(job.job_id, settings=get_settings())
    assert result.passed is False
    assert result.verification_kind == "setup_failed"
    assert result.completed is False
    job2 = ledger.get_job(job.job_id)
    assert job2 is not None
    assert job2.verification and job2.verification["kind"] == "setup_failed"
    assert job2.destroyed_at is None
    assert job2.sandbox_id == "env-fail"


def test_http_probe_failure_is_setup_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed(
        WEBAPP_PROFILE["source"]["url"],
        WEBAPP_PROFILE,
        commit=WEBAPP_PROFILE["source"]["commit"],
    )

    def _exec(environment_id: str, cmd: Any, **kwargs: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "http_code" in joined or "wget" in joined or "curl" in joined:
            return ExecResult("http_code:500\n", "", 1)
        return ExecResult("1\n", "", 0)

    monkeypatch.setattr("verify.exec_command", _exec)
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is False
    assert result.verification_kind == "setup_failed"
    job = get_ledger().get_job(job_id)
    assert job is not None
    # Evidence only: finalizer owns terminal status + destroy (PRODUCT_FIXES §1).
    assert job.status == "verifying"
    assert job.status not in {"failed", "completed", "cancelled"}
    assert job.readiness and job.readiness.get("passed") is False
    assert job.verification and job.verification.get("kind") == "setup_failed"
    assert job.destroyed_at is None
    assert get_ledger().get_receipt(job_id) is None
