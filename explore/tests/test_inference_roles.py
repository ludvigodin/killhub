"""Plane 1 role routing and accounting through explicit Vultr clients and a real ledger."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from agent import (
    AgentError,
    EnvironmentAgent,
    InferenceResult,
    chat_completion,
    record_inference_usage,
)
from config import Settings
from inference_extras import draft_vuln_review
from jobs import get_ledger, reset_ledger_for_tests

_TARGET = "https://github.com/a/b"


@pytest.fixture
def settings(tmp_path: Path) -> Iterator[Settings]:
    """Use a temporary ledger and explicit test credentials, independent of .env."""
    reset_ledger_for_tests()
    try:
        yield Settings(
            _env_file=None,
            LEDGER_URL=f"sqlite:///{tmp_path / 'roles.db'}",
            ADMISSION_STORE="memory",
            INFERENCE_BUDGET_TOKENS_ROLLING=0,
            INFERENCE_BUDGET_TOKENS_PER_JOB=200_000,
            VULTR_INFERENCE_BASE_URL="https://api.vultrinference.com/v1",
            VULTR_INFERENCE_API_KEY="test-key",
            VULTR_INFERENCE_MODEL="default-model",
            VULTR_INFERENCE_MODEL_PLANNER="planner-model",
            VULTR_INFERENCE_MODEL_REVIEW="review-model",
            VULTR_RAG_SEED_FINDINGS=False,
            ENABLE_VULN_REVIEW_LLM=True,
            OPENCODE_CONFIG="",
            OPENCODE_MODEL="",
        )
    finally:
        reset_ledger_for_tests()


def test_environment_agent_uses_planner_model(settings: Settings) -> None:
    """The planner uses its override and records tokens under that role."""
    ledger = get_ledger(settings)
    job = ledger.create_job(_TARGET, env_ttl_seconds=3600)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "planner-model"
        assert body["temperature"] == 0.1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = EnvironmentAgent(job.job_id, settings=settings).infer(
            [{"role": "user", "content": "Reply with ok"}], client=client
        )
    assert result.model == "planner-model"
    snapshot = ledger.get_snapshot(job.job_id)
    assert snapshot is not None
    assert snapshot["inference_usage"]["total_tokens"] == 4
    assert snapshot["inference_usage"]["by_role"]["planner"] == {
        "model": "planner-model",
        "prompt_tokens": 3,
        "completion_tokens": 1,
        "total_tokens": 4,
        "calls": 1,
    }
    # Optional unscoped calls still contribute to the job's aggregate usage.
    usage = record_inference_usage(job.job_id, result, settings=settings)
    assert usage["total_tokens"] == 8
    assert usage["by_role"] == snapshot["inference_usage"]["by_role"]


@pytest.mark.parametrize(
    ("job_budget", "spent", "expected_total"), [(200_000, 39_990, 40_003), (100, 90, 103)]
)
def test_planner_persists_usage_before_rejecting_over_budget_response(
    settings: Settings, job_budget: int, spent: int, expected_total: int
) -> None:
    """Input charges can exceed the remaining budget, but cannot erase recorded usage."""
    settings = settings.model_copy(update={"inference_budget_tokens_per_job": job_budget})
    ledger = get_ledger(settings)
    job = ledger.create_job(_TARGET, env_ttl_seconds=3600)
    record_inference_usage(
        job.job_id,
        InferenceResult("planner-model", "ok", spent, 0, spent, {}),
        settings=settings,
        role="planner",
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert json.loads(request.content)["max_completion_tokens"] == 10
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 5},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for _ in range(2):
            with pytest.raises(AgentError) as err:
                chat_completion(
                    [{"role": "user", "content": "hi"}],
                    job_id=job.job_id,
                    settings=settings,
                    role="planner",
                    client=client,
                )
            assert err.value.code == "inference_budget"
    assert len(requests) == 1
    refreshed = ledger.get_job(job.job_id)
    assert refreshed is not None and refreshed.inference_usage is not None
    assert refreshed.inference_usage["total_tokens"] == expected_total
    assert refreshed.inference_usage["by_role"]["planner"]["total_tokens"] == expected_total


@pytest.mark.parametrize("collection", ["", "killhub_advisories"])
@pytest.mark.parametrize(
    ("default_model", "review_model"), [("", "review-model"), ("default-model", "")]
)
def test_draft_vuln_review_routes_and_records_model(
    settings: Settings, collection: str, default_model: str, review_model: str
) -> None:
    """Both review transports accept the override or the default alone."""
    settings = settings.model_copy(
        update={
            "vultr_inference_model": default_model,
            "vultr_inference_model_review": review_model,
            "vultr_rag_collection": collection,
        }
    )
    expected_model = review_model or default_model
    ledger = get_ledger(settings)
    job = ledger.create_job(_TARGET, env_ttl_seconds=3600)

    def handler(request: httpx.Request) -> httpx.Response:
        suffix = "/RAG" if collection else ""
        assert str(request.url) == f"https://api.vultrinference.com/v1/chat/completions{suffix}"
        body = json.loads(request.content)
        assert body["model"] == expected_model
        assert body["temperature"] == 0
        assert body["max_tokens" if collection else "max_completion_tokens"] == 30_000
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Advisory recorded [sca-1]."}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )

    findings = [{"id": "sca-1", "source": "sca", "severity": "info", "title": "Advisory"}]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert draft_vuln_review(findings, job_id=job.job_id, settings=settings, client=client)
    snapshot = ledger.get_snapshot(job.job_id)
    assert snapshot is not None
    assert snapshot["inference_usage"]["total_tokens"] == 6
    assert snapshot["inference_usage"]["by_role"]["review"] == {
        "model": expected_model,
        "prompt_tokens": 4,
        "completion_tokens": 2,
        "total_tokens": 6,
        "calls": 1,
    }
