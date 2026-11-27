"""Optional Vultr Inference extras: embeddings, RAG, vision (D75 under D25).

Plane 1 only. All calls go through api.vultrinference.com. Fail closed to
non-LLM / non-vision behavior when unset or on transport/budget errors.
Never injects secrets into sandboxes; never gates job completion (D31).
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from agent import (
    AgentError,
    InferenceResult,
    ensure_inference_ready,
    load_trusted_config,
    record_inference_usage,
    resolve_inference_model,
)
from config import Settings, get_settings

logger = logging.getLogger("killhub.inference_extras")

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SECRETISH = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|authorization|bearer)\s*[:=]\s*\S+"
)
_CANARYISH = re.compile(r"CKEY_[0-9a-fA-F]{20,}|KILLHUB_CANARY_[A-Z0-9_]+")


@dataclass(frozen=True)
class EmbeddingResult:
    model: str
    embeddings: list[list[float]]
    prompt_tokens: int
    total_tokens: int
    raw: dict[str, Any]


@dataclass(frozen=True)
class VectorItemResult:
    collection: str
    count: int
    raw: dict[str, Any] | list[Any]


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolve_embedding_model(settings: Settings | None = None) -> str | None:
    cfg = settings or get_settings()
    model = (cfg.vultr_inference_embedding_model or "").strip()
    return model or None


def resolve_vision_model(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    vision = (cfg.vultr_inference_vision_model or "").strip()
    if vision:
        return vision
    return resolve_inference_model(cfg)


def resolve_rag_collection(settings: Settings | None = None) -> str | None:
    cfg = settings or get_settings()
    collection = (cfg.vultr_rag_collection or "").strip()
    return collection or None


def redact_inference_text(text: str) -> str:
    cleaned = _SECRETISH.sub(r"\1=[redacted]", text or "")
    cleaned = _CANARYISH.sub("[redacted]", cleaned)
    return cleaned


def _parse_chat_response(
    data: dict[str, Any],
    *,
    fallback_model: str,
) -> InferenceResult:
    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        content = str(msg.get("content") or "").strip()
        if not content:
            content = str(msg.get("reasoning") or "").strip()
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    return InferenceResult(
        model=str(data.get("model") or fallback_model),
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        raw=data if isinstance(data, dict) else {},
    )


def _post_json(
    path: str,
    payload: dict[str, Any],
    *,
    settings: Settings,
    timeout: float,
    client: httpx.Client | None,
) -> dict[str, Any]:
    """POST to Vultr Inference; path is relative to the /v1 base (e.g. /embeddings)."""
    load_trusted_config(settings)
    base, api_key, _model = ensure_inference_ready(settings)
    url = f"{base.rstrip('/')}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "killhub-explore/0.1",
    }
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        resp = http.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise AgentError(
            f"Vultr inference request failed: {exc.__class__.__name__}",
            code="inference_transport",
        ) from exc
    finally:
        if owns_client:
            http.close()

    if resp.status_code >= 400:
        raise AgentError(
            f"Vultr inference HTTP {resp.status_code}",
            code="inference_http_error",
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise AgentError("Vultr inference returned non-JSON", code="inference_bad_body") from exc
    if not isinstance(data, dict):
        raise AgentError("Vultr inference returned non-object JSON", code="inference_bad_body")
    return data


def create_embeddings(
    inputs: str | list[str],
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    input_type: str | None = None,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
) -> EmbeddingResult:
    """OpenAI-compatible POST /embeddings on Vultr Serverless Inference."""
    cfg = settings or get_settings()
    model = resolve_embedding_model(cfg)
    if not model:
        raise AgentError(
            "VULTR_INFERENCE_EMBEDDING_MODEL unset — embeddings unavailable",
            code="embeddings_disabled",
        )
    texts = [inputs] if isinstance(inputs, str) else list(inputs)
    if not texts:
        raise AgentError("embeddings input is empty", code="embeddings_empty")
    # Cap batch size for budget (API allows 2048; keep v1 bounded).
    capped = [redact_inference_text(t)[:4000] for t in texts[:32]]
    payload: dict[str, Any] = {"model": model, "input": capped}
    if input_type:
        payload["input_type"] = input_type

    data = _post_json(
        "/embeddings",
        payload,
        settings=cfg,
        timeout=timeout,
        client=client,
    )
    rows = data.get("data") or []
    embeddings: list[list[float]] = []
    for row in sorted(rows, key=lambda r: int((r or {}).get("index") or 0)):
        if not isinstance(row, dict):
            continue
        emb = row.get("embedding")
        if isinstance(emb, list):
            embeddings.append([float(x) for x in emb])
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens)
    result = EmbeddingResult(
        model=str(data.get("model") or model),
        embeddings=embeddings,
        prompt_tokens=prompt_tokens,
        total_tokens=total_tokens,
        raw=data,
    )
    if job_id is not None:
        # Record toward the same per-job budget (D40).
        record_inference_usage(
            job_id,
            InferenceResult(
                model=result.model,
                content="",
                prompt_tokens=result.prompt_tokens,
                completion_tokens=0,
                total_tokens=result.total_tokens,
                raw=result.raw,
            ),
            settings=cfg,
        )
    return result


def add_vector_store_items(
    collection: str,
    texts: list[str],
    *,
    settings: Settings | None = None,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
    auto_chunk: bool = True,
) -> VectorItemResult:
    """POST /vector_store/{id}/items — fail closed if collection empty."""
    cfg = settings or get_settings()
    coll = (collection or "").strip()
    if not coll:
        raise AgentError("VULTR_RAG_COLLECTION unset", code="rag_disabled")
    items = [redact_inference_text(t).strip() for t in texts if (t or "").strip()]
    if not items:
        return VectorItemResult(collection=coll, count=0, raw={})

    # One request per item keeps payloads small (item max 2000 chars when not chunked).
    responses: list[Any] = []
    for text in items[:40]:
        body: dict[str, Any] = {"content": text[:2000]}
        if auto_chunk and len(text) > 2000:
            body = {"content": text[:8000], "auto_chunk": True}
        data = _post_json(
            f"/vector_store/{coll}/items",
            body,
            settings=cfg,
            timeout=timeout,
            client=client,
        )
        responses.append(data)
    return VectorItemResult(collection=coll, count=len(responses), raw=responses)


def rag_chat_completion(
    messages: list[dict[str, Any]],
    *,
    collection: str,
    job_id: str | None = None,
    settings: Settings | None = None,
    model: str | None = None,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
) -> InferenceResult:
    """POST /chat/completions/RAG against a Vultr vector_store collection."""
    cfg = settings or get_settings()
    coll = (collection or "").strip()
    if not coll:
        raise AgentError("VULTR_RAG_COLLECTION unset", code="rag_disabled")
    chat_model = (model or "").strip() or resolve_inference_model(cfg)
    payload = {
        "model": chat_model,
        "collection": coll,
        "messages": messages,
        "temperature": 0,
    }
    data = _post_json(
        "/chat/completions/RAG",
        payload,
        settings=cfg,
        timeout=timeout,
        client=client,
    )
    result = _parse_chat_response(data, fallback_model=chat_model)
    if job_id is not None:
        record_inference_usage(job_id, result, settings=cfg)
    return result


def vision_chat_completion(
    messages: list[dict[str, Any]],
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    timeout: float = 90.0,
    client: httpx.Client | None = None,
) -> InferenceResult:
    """Multimodal chat/completions using VULTR_INFERENCE_VISION_MODEL (or chat model)."""
    cfg = settings or get_settings()
    model = resolve_vision_model(cfg)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_completion_tokens": 256,
    }
    data = _post_json(
        "/chat/completions",
        payload,
        settings=cfg,
        timeout=timeout,
        client=client,
    )
    result = _parse_chat_response(data, fallback_model=model)
    if job_id is not None:
        record_inference_usage(job_id, result, settings=cfg)
    return result


def advisory_snippets_from_findings(findings: list[dict[str, Any]]) -> list[str]:
    """Build short, redacted advisory passages suitable for embeddings / vector items."""
    snippets: list[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "").strip()
        if not fid:
            continue
        source = str(f.get("source") or "finding")
        sev = str(f.get("severity") or "info")
        title = str(f.get("title") or fid)
        pkg = str(f.get("package") or "")
        url = str(f.get("advisory_url") or "")
        detail = f.get("detail") if isinstance(f.get("detail"), dict) else {}
        osv = ""
        if isinstance(detail, dict):
            osv = str(detail.get("osv_id") or "")
        parts = [
            f"finding_id={fid}",
            f"source={source}",
            f"severity={sev}",
            f"title={title}",
        ]
        if pkg:
            parts.append(f"package={pkg}")
        if osv:
            parts.append(f"osv_id={osv}")
        if url:
            parts.append(f"advisory_url={url}")
        snippets.append(redact_inference_text(" | ".join(parts)))
    return snippets


def load_vuln_review_system_prompt() -> str:
    path = PROMPTS_DIR / "vuln_review.md"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return (
        "Summarize findings. Every claim must cite finding ids like [sca-1]. "
        "Do not invent CVEs. Do not weaponize."
    )


def _findings_user_payload(findings: list[dict[str, Any]]) -> str:
    lines = ["Findings (cite only these ids):"]
    for f in findings[:60]:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        lines.append(
            "- "
            f"[{f.get('id')}] severity={f.get('severity')} source={f.get('source')} "
            f"package={f.get('package') or '-'} title={f.get('title')}"
        )
        url = f.get("advisory_url")
        if url:
            lines.append(f"  advisory_url={url}")
    lines.append("")
    lines.append("Write a cite-checked plain-text summary.")
    return redact_inference_text("\n".join(lines))


def draft_vuln_review(
    findings: list[dict[str, Any]],
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """
    Optional AI draft for cite-checked vuln_review (D48).

    Uses RAG when VULTR_RAG_COLLECTION is set; otherwise ordinary chat.
    Returns None on disable / error so callers keep the deterministic summary.
    """
    cfg = settings or get_settings()
    if not _truthy(cfg.enable_vuln_review_llm):
        return None
    if not findings:
        return None
    try:
        ensure_inference_ready(cfg)
    except AgentError:
        return None

    system = load_vuln_review_system_prompt()
    user = _findings_user_payload(findings)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    collection = resolve_rag_collection(cfg)

    # Optionally seed vector items from this job's findings (fail closed).
    if collection and _truthy(cfg.vultr_rag_seed_findings):
        try:
            snippets = advisory_snippets_from_findings(findings)
            add_vector_store_items(collection, snippets, settings=cfg, client=client)
        except AgentError as exc:
            logger.info("RAG seed skipped: %s", exc.message)

    try:
        if collection:
            result = rag_chat_completion(
                messages,
                collection=collection,
                job_id=job_id,
                settings=cfg,
                client=client,
            )
        else:
            from agent import chat_completion

            result = chat_completion(
                messages,
                job_id=job_id,
                settings=cfg,
                client=client,
            )
        draft = redact_inference_text(result.content).strip()
        return draft or None
    except AgentError as exc:
        logger.info("vuln_review LLM draft skipped: %s (%s)", exc.message, exc.code)
        return None


def maybe_seed_embeddings_for_findings(
    findings: list[dict[str, Any]],
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> EmbeddingResult | None:
    """
    Document-only embeddings helper when an embedding model is configured.

    Used for advisory corpus indexing; does not change vuln_review output.
    """
    cfg = settings or get_settings()
    if not resolve_embedding_model(cfg):
        return None
    if not findings:
        return None
    snippets = advisory_snippets_from_findings(findings)
    if not snippets:
        return None
    try:
        return create_embeddings(
            snippets,
            job_id=job_id,
            settings=cfg,
            input_type="search_document",
            client=client,
        )
    except AgentError as exc:
        logger.info("embeddings skipped: %s (%s)", exc.message, exc.code)
        return None


def _png_data_uri(path: Path, *, max_bytes: int = 1_500_000) -> str | None:
    if not path.is_file():
        return None
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        return None
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def caption_screenshot(
    image_path: Path | str,
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    client: httpx.Client | None = None,
) -> str | None:
    """
    Optional UI sanity caption for a copied Plane-1 screenshot (D31 / D75).

    ENABLE_SCREENSHOT_VISION must be true. Never raises into job failure paths.
    Never sends canary/secret plaintext in the text prompt.
    """
    cfg = settings or get_settings()
    if not _truthy(cfg.enable_screenshot_vision):
        return None
    try:
        ensure_inference_ready(cfg)
    except AgentError:
        return None

    path = Path(image_path)
    uri = _png_data_uri(path)
    if not uri:
        return None

    prompt = (
        "Describe this webapp screenshot for Killhub evidence in one short sentence. "
        "Focus on visible UI state (blank page, error banner, login form, content). "
        "Do not invent credentials. Do not repeat any secrets or tokens if visible — "
        "say [redacted] instead."
    )
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": uri}},
            ],
        }
    ]
    try:
        result = vision_chat_completion(
            messages,
            job_id=job_id,
            settings=cfg,
            client=client,
        )
        caption = redact_inference_text(result.content).strip()
        return caption[:240] or None
    except AgentError as exc:
        logger.info("screenshot vision skipped: %s (%s)", exc.message, exc.code)
        return None
