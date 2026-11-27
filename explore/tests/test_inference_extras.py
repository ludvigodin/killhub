"""Vultr Inference extras — embeddings / RAG / vision (D75). Mocked HTTP only."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from config import get_settings
from inference_extras import (
    advisory_snippets_from_findings,
    caption_screenshot,
    create_embeddings,
    draft_vuln_review,
    rag_chat_completion,
    redact_inference_text,
)
from jobs import reset_ledger_for_tests
from vulnscan import cite_checked_review


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("VULTR_INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "qwen3.8-flash-next")
    monkeypatch.setenv("ENABLE_VULN_REVIEW_LLM", "true")
    monkeypatch.setenv("ENABLE_SCREENSHOT_VISION", "false")
    monkeypatch.setenv("VULTR_RAG_COLLECTION", "")
    monkeypatch.setenv("VULTR_RAG_SEED_FINDINGS", "false")
    monkeypatch.delenv("VULTR_INFERENCE_EMBEDDING_MODEL", raising=False)
    monkeypatch.delenv("VULTR_INFERENCE_VISION_MODEL", raising=False)
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def _mock_transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_redact_strips_canaries_and_secrets() -> None:
    text = "token=sekrit CKEY_abcdef0123456789abcdef012345 and ok"
    out = redact_inference_text(text)
    assert "sekrit" not in out
    assert "CKEY_" not in out
    assert "[redacted]" in out


def test_embeddings_disabled_without_model() -> None:
    with pytest.raises(Exception) as err:
        create_embeddings("hello")
    assert getattr(err.value, "code", "") == "embeddings_disabled"


def test_create_embeddings_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VULTR_INFERENCE_EMBEDDING_MODEL", "qwen3-embedding-4b")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "qwen3-embedding-4b"
        assert body["input_type"] == "search_document"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "qwen3-embedding-4b",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
        )

    with _mock_transport(handler) as client:
        result = create_embeddings(
            ["advisory text"],
            input_type="search_document",
            client=client,
        )
    assert result.total_tokens == 4
    assert result.embeddings == [[0.1, 0.2]]


def test_rag_chat_completion_mocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/chat/completions/RAG" in str(request.url)
        body = json.loads(request.content.decode("utf-8"))
        assert body["collection"] == "killhub_advisories"
        return httpx.Response(
            200,
            json={
                "model": "qwen3.8-flash-next",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "High risk in lodash [sca-1].",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    with _mock_transport(handler) as client:
        result = rag_chat_completion(
            [{"role": "user", "content": "summarize"}],
            collection="killhub_advisories",
            client=client,
        )
    assert "[sca-1]" in result.content
    assert result.total_tokens == 15


def test_draft_vuln_review_fail_closed_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VULTR_RAG_COLLECTION", "")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    findings = [
        {
            "id": "sca-1",
            "severity": "high",
            "title": "Prototype pollution",
            "source": "sca",
        }
    ]
    with _mock_transport(handler) as client:
        draft = draft_vuln_review(findings, client=client)
    assert draft is None
    # Deterministic path still works.
    assert "[sca-1]" in cite_checked_review(findings)


def test_draft_vuln_review_llm_then_cite_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "model": "qwen3.8-flash-next",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Prototype pollution in lodash [sca-1]. "
                                "Also remote code execution in imaginary-pkg."
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 12,
                    "total_tokens": 20,
                },
            },
        )

    findings = [
        {
            "id": "sca-1",
            "severity": "high",
            "title": "Prototype pollution",
            "source": "sca",
        }
    ]
    with _mock_transport(handler) as client:
        draft = draft_vuln_review(findings, client=client)
    assert draft is not None
    out = cite_checked_review(findings, draft=draft)
    assert "[sca-1]" in out
    assert "imaginary-pkg" not in out


def test_caption_screenshot_disabled_by_default(tmp_path: Path) -> None:
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    assert caption_screenshot(png) is None


def test_caption_screenshot_vision_mocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENABLE_SCREENSHOT_VISION", "true")
    monkeypatch.setenv("VULTR_INFERENCE_VISION_MODEL", "vision-model-test")
    get_settings.cache_clear()
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "vision-model-test"
        content = body["messages"][0]["content"]
        assert isinstance(content, list)
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        return httpx.Response(
            200,
            json={
                "model": "vision-model-test",
                "choices": [
                    {
                        "message": {
                            "content": "Landing page with a Get Started button.",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 8,
                    "total_tokens": 48,
                },
            },
        )

    with _mock_transport(handler) as client:
        caption = caption_screenshot(png, client=client)
    assert caption is not None
    assert "Landing page" in caption


def test_advisory_snippets_include_finding_ids() -> None:
    snippets = advisory_snippets_from_findings(
        [
            {
                "id": "sca-abc",
                "severity": "medium",
                "title": "DoS",
                "package": "left-pad@1.0.0",
                "source": "sca",
                "advisory_url": "https://osv.dev/vulnerability/GHSA-x",
                "detail": {"osv_id": "GHSA-x"},
            }
        ]
    )
    assert len(snippets) == 1
    assert "finding_id=sca-abc" in snippets[0]
    assert "GHSA-x" in snippets[0]
