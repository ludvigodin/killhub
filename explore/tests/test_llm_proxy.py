"""Plane 1 tests of the fixed inference check using inert provider responses.

A real SQLite ledger covers job authorization, replacement, and durable usage;
the mock HTTP transport never needs provider or sandbox credentials.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from config import Settings
from ledger import Ledger
from llm_proxy import InferenceSmokeError, InferenceSmokeSession


@pytest.fixture
def smoke(tmp_path: Path) -> Iterator[tuple[Ledger, str, Settings]]:
    """Record the current generation with synthetic configuration and credentials."""
    ledger = Ledger.from_url(f"sqlite:///{tmp_path / 'smoke.db'}")
    job = ledger.create_job(
        "https://github.com/example/benign", env_ttl_seconds=3600, status="verifying"
    )
    ledger.update_job_fields(job.job_id, sandbox_id="trusted-fixture", current_sandbox_generation=1)
    settings = Settings(
        _env_file=None,
        VULTR_INFERENCE_BASE_URL="https://api.vultrinference.com/v1",
        VULTR_INFERENCE_API_KEY="synthetic-plane-1-key",
        VULTR_INFERENCE_MODEL="trusted-model",
        INFERENCE_BUDGET_TOKENS_PER_JOB=200_000,
    )
    try:
        yield ledger, job.job_id, settings
    finally:
        ledger.close()


def _provider_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "synthetic-private-output"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11},
        },
    )


def test_only_scoped_bearer_reaches_fixed_provider_check(
    smoke: tuple[Ledger, str, Settings],
) -> None:
    """Only Plane 1's credential and fixed request go upstream."""
    ledger, job_id, settings = smoke
    session = InferenceSmokeSession(job_id=job_id, generation=1, ledger=ledger, settings=settings)
    grant = f"Bearer {session.bearer()}"
    calls = []

    def request_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["Authorization"] == "Bearer synthetic-plane-1-key"
        assert session.bearer() not in request.content.decode()
        body = json.loads(request.content)
        assert body["model"] == "trusted-model"
        assert body["messages"] == [{"role": "user", "content": "Reply with OK."}]
        assert body["max_completion_tokens"] == 32
        assert "tools" not in body
        return _provider_response()

    with httpx.Client(transport=httpx.MockTransport(request_handler)) as client:
        for bad_job, bad_generation, bad_grant in [
            ("different-job", 1, grant),
            (job_id, 2, grant),
            (job_id, 1, "Bearer incorrect"),
        ]:
            with pytest.raises(InferenceSmokeError) as denied:
                session.run(
                    job_id=bad_job,
                    generation=bad_generation,
                    authorization=bad_grant,
                    client=client,
                )
            assert denied.value.status_code == 403
        assert calls == []
        result = session.run(job_id=job_id, generation=1, authorization=grant, client=client)
    assert calls == ["https://api.vultrinference.com/v1/chat/completions"]
    assert result == {"turns": 1, "total_tokens": 11}
    job = ledger.get_job(job_id)
    assert job is not None
    assert job.inference_usage["by_role"]["guest_smoke"]["total_tokens"] == 11


@pytest.mark.parametrize(
    "fields",
    [
        {"current_sandbox_generation": 2},
        {"expires_at": "2026-01-01T00:00:00Z"},
        {"cancel_requested_at": "2026-01-01T00:00:00Z"},
        {"destroyed_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_replacement_expiry_and_cancel_invalidate_grant(
    smoke: tuple[Ledger, str, Settings], fields: dict
) -> None:
    """Revocation comes from the durable job, even with an earlier valid bearer."""
    ledger, job_id, settings = smoke
    session = InferenceSmokeSession(job_id=job_id, generation=1, ledger=ledger, settings=settings)
    ledger.update_job_fields(job_id, **fields)
    with pytest.raises(InferenceSmokeError) as denied:
        session.run(job_id=job_id, generation=1, authorization=f"Bearer {session.bearer()}")
    assert denied.value.code == "inference_session_inactive"


@pytest.mark.parametrize("previous_calls,previous_tokens", [(12, 132), (1, 59_990)])
def test_existing_job_usage_blocks_before_outbound_request(
    smoke: tuple[Ledger, str, Settings], previous_calls: int, previous_tokens: int
) -> None:
    """A new grant cannot reset recorded turn or token limits."""
    ledger, job_id, settings = smoke
    ledger.update_job_fields(
        job_id,
        inference_usage={
            "total_tokens": previous_tokens,
            "by_role": {"guest_smoke": {"total_tokens": previous_tokens, "calls": previous_calls}},
        },
    )
    session = InferenceSmokeSession(job_id=job_id, generation=1, ledger=ledger, settings=settings)
    with pytest.raises(InferenceSmokeError) as capped:
        session.run(job_id=job_id, generation=1, authorization=f"Bearer {session.bearer()}")
    assert capped.value.status_code == 429
    assert capped.value.code == "kill_switch_layer1"


def test_provider_failure_uses_safe_error_and_reserves_budget(
    smoke: tuple[Ledger, str, Settings],
) -> None:
    """An ambiguous provider error never returns its body or frees a reservation."""
    ledger, job_id, settings = smoke
    settings = settings.model_copy(update={"inference_budget_tokens_per_job": 1024})
    session = InferenceSmokeSession(job_id=job_id, generation=1, ledger=ledger, settings=settings)
    grant = f"Bearer {session.bearer()}"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(500, text="synthetic-private-error"))
    ) as client:
        with pytest.raises(InferenceSmokeError, match="^inference_check_failed$") as invalid:
            session.run(job_id=job_id, generation=1, authorization=grant, client=client)
        assert invalid.value.status_code == 502
        with pytest.raises(InferenceSmokeError, match="^kill_switch_layer1$"):
            session.run(job_id=job_id, generation=1, authorization=grant, client=client)


def test_redirect_cannot_forward_credentials(smoke: tuple[Ledger, str, Settings]) -> None:
    """Even a redirect from the configured provider cannot forward the key."""
    ledger, job_id, settings = smoke
    session = InferenceSmokeSession(job_id=job_id, generation=1, ledger=ledger, settings=settings)
    requests = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://example.invalid/"})

    with httpx.Client(transport=httpx.MockTransport(redirect), follow_redirects=True) as client:
        with pytest.raises(InferenceSmokeError, match="^inference_check_failed$"):
            session.run(
                job_id=job_id,
                generation=1,
                authorization=f"Bearer {session.bearer()}",
                client=client,
            )
    assert requests == ["https://api.vultrinference.com/v1/chat/completions"]
