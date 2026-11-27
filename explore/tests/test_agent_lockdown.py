"""OpenCode lockdown + Vultr inference gating (D38, D25)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent import (
    AgentError,
    EnvironmentAgent,
    assert_vultr_inference,
    chat_completion,
    load_trusted_config,
    prove_inference,
    record_inference_usage,
    refuse_repo_config_authority,
    trusted_config_path,
)
from config import get_settings
from harness_tools import HarnessTools
from jobs import get_ledger, reset_ledger_for_tests


@pytest.fixture(autouse=True)
def _clear_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    db = tmp_path / "ledger.db"
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{db.as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def test_trusted_config_loads_and_denies_shell() -> None:
    data = load_trusted_config()
    policies = data["policies"]
    assert any(
        p.get("action") == "tool.use"
        and str(p.get("resource", "")).startswith("shell")
        and p.get("effect") == "deny"
        for p in policies
    )
    assert any(
        p.get("action") == "provider.use"
        and p.get("resource") == "vultr"
        and p.get("effect") == "allow"
        for p in policies
    )
    assert set((data.get("mcp") or {}).get("servers") or {}) == {"killhub-harness"}


def test_non_vultr_base_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.openai.com/v1")
    get_settings.cache_clear()
    with pytest.raises(AgentError) as err:
        assert_vultr_inference()
    assert err.value.code == "inference_forbidden"
    get_settings.cache_clear()


def test_http_base_url_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "http://api.vultrinference.com/v1")
    get_settings.cache_clear()
    with pytest.raises(AgentError) as err:
        assert_vultr_inference()
    assert err.value.code == "inference_forbidden"
    get_settings.cache_clear()


def test_missing_api_key_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "somemodel")
    get_settings.cache_clear()
    with pytest.raises(AgentError) as err:
        prove_inference()
    assert err.value.code == "inference_unavailable"
    get_settings.cache_clear()


def test_refuse_repo_agents_md(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# hostile", encoding="utf-8")
    with pytest.raises(AgentError) as err:
        refuse_repo_config_authority(agents)
    assert err.value.code == "untrusted_repo_input"

    project = tmp_path / ".opencode" / "opencode.json"
    project.parent.mkdir()
    project.write_text("{}", encoding="utf-8")
    with pytest.raises(AgentError) as err2:
        refuse_repo_config_authority(project)
    assert err2.value.code == "untrusted_repo_input"


def test_harness_tools_deny_unknown() -> None:
    tools = HarnessTools("job-x")
    assert "create" in tools.list_tools()
    with pytest.raises(Exception) as err:
        tools.call("shell")
    assert getattr(err.value, "code", "") == "tool_denied"


def test_record_inference_usage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent import InferenceResult

    monkeypatch.setenv("INFERENCE_BUDGET_TOKENS_PER_JOB", "1000")
    get_settings.cache_clear()
    ledger = get_ledger()
    job = ledger.create_job(
        "https://github.com/heroku/nodejs-getting-started",
        env_ttl_seconds=3600,
    )
    result = InferenceResult(
        model="test-model",
        content="ok",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        raw={},
    )
    usage = record_inference_usage(job.job_id, result)
    assert usage["total_tokens"] == 15
    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.inference_model == "test-model"
    assert refreshed.inference_usage["calls"] == 1
    get_settings.cache_clear()


def test_chat_completion_uses_vultr_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "qwen2.5-coder-32b")
    get_settings.cache_clear()

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        body = json.loads(request.content.decode("utf-8"))
        seen["model"] = body.get("model")
        assert "api.vultrinference.com" in str(request.url)
        assert "openai.com" not in str(request.url)
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5-coder-32b",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 3,
                    "completion_tokens": 1,
                    "total_tokens": 4,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    result = chat_completion(
        [{"role": "user", "content": "hi"}],
        client=client,
    )
    assert result.content == "ok"
    assert seen["url"] == "https://api.vultrinference.com/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["model"] == "qwen2.5-coder-32b"
    get_settings.cache_clear()


def test_chat_completion_falls_back_to_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "qwen3.8-flash-next")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "qwen3.8-flash-next",
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "reasoning": "ok",
                        }
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = chat_completion([{"role": "user", "content": "hi"}], client=client)
    assert result.content == "ok"
    get_settings.cache_clear()


def test_environment_agent_binds_trusted_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
    get_settings.cache_clear()
    ledger = get_ledger()
    job = ledger.create_job(
        "https://github.com/heroku/nodejs-getting-started",
        env_ttl_seconds=3600,
    )
    agent = EnvironmentAgent(job.job_id)
    assert agent.config_path == trusted_config_path()
    assert "exec" in agent.list_tools()
    get_settings.cache_clear()
