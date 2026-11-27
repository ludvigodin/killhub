"""Environment Agent — locked-down OpenCode + Vultr Serverless Inference (D38, D25).

Plane 1 only. Never loads submitted-repo `.opencode` / `AGENTS.md` as authority.
Inference is Vultr Serverless Inference exclusively; missing keys fail closed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from config import Settings, get_settings
from harness_tools import HarnessTools
from jobs import get_ledger

logger = logging.getLogger("killhub.agent")

VULTR_INFERENCE_HOST = "api.vultrinference.com"
DEFAULT_TRUSTED_CONFIG = Path(__file__).resolve().parent / "opencode" / "opencode.json"
PROVIDER_ID = "vultr"

_UNTRUSTED_REPO_DOC_NAMES = frozenset({"agents.md", "agent.md"})


class AgentError(Exception):
    def __init__(self, message: str, *, code: str = "agent_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass(frozen=True)
class InferenceResult:
    model: str
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw: dict[str, Any]


def trusted_config_path(settings: Settings | None = None) -> Path:
    """Host-owned OpenCode config only — never a path from a submitted checkout."""
    cfg = settings or get_settings()
    raw = (cfg.opencode_config or "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_TRUSTED_CONFIG
    resolved = path.resolve()
    if not resolved.is_file():
        raise AgentError(
            f"trusted OpenCode config missing: {resolved}",
            code="opencode_config_missing",
        )
    # Reject anything that looks like submitted-repo project config.
    name = resolved.name.lower()
    parent = resolved.parent.name.lower()
    if parent in {".opencode", "opencode"} and name in {
        "opencode.json",
        "opencode.jsonc",
    }:
        # Bundled explore/opencode/ is allowed; nested .opencode is not.
        if parent == ".opencode":
            raise AgentError(
                "refusing project .opencode config as authority (D38)",
                code="untrusted_opencode_config",
            )
    if "node_modules" in resolved.parts or ".git" in resolved.parts:
        raise AgentError(
            "refusing OpenCode config under VCS/vendor trees",
            code="untrusted_opencode_config",
        )
    return resolved


def refuse_repo_config_authority(path: Path | str) -> None:
    """Raise if a path is submitted-repo OpenCode/AGENTS material used as authority."""
    p = Path(path)
    parts_lower = {part.lower() for part in p.parts}
    name = p.name.lower()
    if ".opencode" in parts_lower or name in _UNTRUSTED_REPO_DOC_NAMES:
        raise AgentError(
            f"submitted-repo path cannot be OpenCode authority: {p}",
            code="untrusted_repo_input",
        )


def normalize_inference_base_url(url: str) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        raise AgentError(
            "VULTR_INFERENCE_BASE_URL is required",
            code="inference_misconfigured",
        )
    parsed = urlparse(cleaned)
    if parsed.scheme != "https":
        raise AgentError(
            "inference base URL must be https",
            code="inference_forbidden",
        )
    host = (parsed.hostname or "").lower()
    if host != VULTR_INFERENCE_HOST:
        raise AgentError(
            f"inference base URL host must be {VULTR_INFERENCE_HOST} (D25); got {host!r}",
            code="inference_forbidden",
        )
    # Require /v1 suffix (OpenAI-compatible root).
    path = parsed.path.rstrip("/") or ""
    if path not in {"/v1", ""}:
        # Allow https://api.vultrinference.com/v1... only
        if not path.startswith("/v1"):
            raise AgentError(
                "inference base URL path must be /v1",
                code="inference_forbidden",
            )
    if path == "":
        cleaned = f"{cleaned}/v1"
    return cleaned


def assert_vultr_inference(settings: Settings | None = None) -> str:
    """Fail closed unless settings point at Vultr Serverless Inference."""
    cfg = settings or get_settings()
    return normalize_inference_base_url(cfg.vultr_inference_base_url)


def load_trusted_config(settings: Settings | None = None) -> dict[str, Any]:
    path = trusted_config_path(settings)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AgentError("trusted OpenCode config must be an object", code="opencode_invalid")
    validate_trusted_config(data, settings=settings)
    return data


def validate_trusted_config(
    data: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> None:
    """Enforce D38 shape: Vultr-only provider + host shell denied."""
    cfg = settings or get_settings()
    base = assert_vultr_inference(cfg)

    providers = data.get("providers") or {}
    if PROVIDER_ID not in providers:
        raise AgentError(
            f"trusted config must define providers.{PROVIDER_ID}",
            code="opencode_invalid",
        )
    provider = providers[PROVIDER_ID]
    settings_block = (provider.get("settings") or {}) if isinstance(provider, dict) else {}
    # baseURL may be an env template — runtime still gated by Settings.
    configured = str(settings_block.get("baseURL") or "")
    if configured and "{env:" not in configured:
        normalize_inference_base_url(configured)
    elif "{env:" in configured and "VULTR_INFERENCE_BASE_URL" not in configured:
        raise AgentError(
            "provider baseURL must bind VULTR_INFERENCE_BASE_URL",
            code="opencode_invalid",
        )

    policies = data.get("policies") or []
    if not isinstance(policies, list) or not policies:
        raise AgentError("trusted config must declare policies", code="opencode_invalid")

    def _allows(action: str, resource: str) -> bool:
        """Last matching statement wins (OpenCode policy order)."""
        decision: bool | None = None
        for stmt in policies:
            if not isinstance(stmt, dict):
                continue
            if stmt.get("action") != action:
                continue
            pat = str(stmt.get("resource") or "")
            if not _resource_match(pat, resource):
                continue
            decision = stmt.get("effect") == "allow"
        return bool(decision)

    if _allows("provider.use", "openai") or _allows("provider.use", "anthropic"):
        raise AgentError(
            "trusted config must not allow non-Vultr providers",
            code="opencode_invalid",
        )
    if not _allows("provider.use", PROVIDER_ID):
        raise AgentError(
            "trusted config must allow provider.use vultr",
            code="opencode_invalid",
        )
    if _allows("tool.use", "shell:id") or _allows("tool.use", "shell:ls"):
        raise AgentError(
            "trusted config must deny host shell tools",
            code="opencode_invalid",
        )
    # Explicit shell deny must be present.
    shell_denied = any(
        isinstance(s, dict)
        and s.get("action") == "tool.use"
        and s.get("effect") == "deny"
        and str(s.get("resource") or "").startswith("shell")
        for s in policies
    )
    if not shell_denied:
        raise AgentError(
            "trusted config must deny tool.use shell:*",
            code="opencode_invalid",
        )

    # Permissions layer (also deny shell).
    perms = data.get("permissions") or []
    if not any(
        isinstance(p, dict) and p.get("action") == "shell" and p.get("effect") == "deny"
        for p in perms
    ):
        raise AgentError(
            "trusted config must deny shell permissions",
            code="opencode_invalid",
        )

    mcp_block = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
    mcp = (mcp_block or {}).get("servers") or {}
    unexpected = set(mcp) - {"killhub-harness"}
    if unexpected:
        raise AgentError(
            f"trusted config MCP servers must be killhub-harness only; got {sorted(unexpected)}",
            code="opencode_invalid",
        )

    logger.debug("trusted OpenCode config ok (base=%s)", base)


def _resource_match(pattern: str, resource: str) -> bool:
    if pattern == "*":
        return True
    # Convert simple * wildcards to regex.
    escaped = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(escaped, resource) is not None


def resolve_inference_model(settings: Settings | None = None) -> str:
    cfg = settings or get_settings()
    model = (cfg.vultr_inference_model or cfg.opencode_model or "").strip()
    if not model:
        raise AgentError(
            "VULTR_INFERENCE_MODEL (or OPENCODE_MODEL) is required",
            code="inference_misconfigured",
        )
    return model


def ensure_inference_ready(settings: Settings | None = None) -> tuple[str, str, str]:
    """Return (base_url, api_key, model) or fail closed."""
    cfg = settings or get_settings()
    base = assert_vultr_inference(cfg)
    key = (cfg.vultr_inference_api_key or "").strip()
    if not key:
        raise AgentError(
            "VULTR_INFERENCE_API_KEY missing — fail closed (D25)",
            code="inference_unavailable",
        )
    model = resolve_inference_model(cfg)
    return base, key, model


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    job_id: str | None = None,
    settings: Settings | None = None,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
) -> InferenceResult:
    """OpenAI-compatible chat call against Vultr Serverless Inference only.

    ``messages[].content`` may be a string or a multimodal content-part array
    (vision / file parts — D75). Provider remains Vultr-only (D25).
    """
    cfg = settings or get_settings()
    load_trusted_config(cfg)  # validate lockdown before any network call
    base, api_key, model = ensure_inference_ready(cfg)
    url = f"{base}/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0,
    }
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

    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        # Reasoning models may fill `reasoning` and leave `content` empty when
        # completion budget is tight; prefer content, fall back to reasoning.
        content = str(msg.get("content") or "").strip()
        if not content:
            content = str(msg.get("reasoning") or "").strip()
    usage = data.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    result = InferenceResult(
        model=str(data.get("model") or model),
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        raw=data if isinstance(data, dict) else {},
    )
    if job_id is not None:
        record_inference_usage(job_id, result, settings=cfg)
    return result


def record_inference_usage(
    job_id: str,
    result: InferenceResult,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Persist inference_model + cumulative usage toward budgets (D40)."""
    cfg = settings or get_settings()
    ledger = get_ledger(cfg)
    job = ledger.get_job(job_id)
    if job is None:
        raise AgentError(f"unknown job_id: {job_id}", code="not_found")

    prev = job.inference_usage if isinstance(job.inference_usage, dict) else {}
    usage = {
        "prompt_tokens": int(prev.get("prompt_tokens") or 0) + result.prompt_tokens,
        "completion_tokens": int(prev.get("completion_tokens") or 0) + result.completion_tokens,
        "total_tokens": int(prev.get("total_tokens") or 0) + result.total_tokens,
        "calls": int(prev.get("calls") or 0) + 1,
        "budget_tokens": cfg.inference_budget_tokens_per_job,
    }
    budget = cfg.inference_budget_tokens_per_job
    if budget > 0 and usage["total_tokens"] > budget:
        ledger.append_event(
            job_id,
            typ="log",
            message="inference budget exceeded",
            payload={"kind": "inference", "usage": usage},
        )
        raise AgentError(
            f"inference budget exceeded ({usage['total_tokens']} > {budget})",
            code="inference_budget",
        )

    # Rolling (cross-job) budget via admission store (D40 / D71).
    try:
        from admission import (
            AdmissionRejected,
            AdmissionStoreError,
            get_admission_store,
        )

        store = get_admission_store(cfg)
        added = int(result.total_tokens or 0)
        store.check_rolling_inference(
            tokens=added,
            budget=cfg.inference_budget_tokens_rolling,
            window_seconds=cfg.inference_budget_rolling_window_seconds,
        )
        store.record_inference_tokens(
            added,
            window_seconds=cfg.inference_budget_rolling_window_seconds,
        )
    except AdmissionRejected as exc:
        ledger.append_event(
            job_id,
            typ="log",
            message="rolling inference budget exceeded",
            payload={"kind": "inference", "usage": usage},
        )
        raise AgentError(exc.message, code=exc.code) from exc
    except AdmissionStoreError as exc:
        logger.error("rolling inference store error: %s", exc)

    ledger.update_job_fields(
        job_id,
        inference_model=result.model,
        inference_usage=usage,
    )
    ledger.append_event(
        job_id,
        typ="log",
        message=f"inference call model={result.model} tokens={result.total_tokens}",
        payload={
            "kind": "inference",
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "usage": usage,
        },
    )
    return usage


def prove_inference(settings: Settings | None = None) -> InferenceResult:
    """Real Vultr call when keys exist; otherwise fail closed (plan 10 Done when)."""
    return chat_completion(
        [{"role": "user", "content": "Reply with exactly: ok"}],
        settings=settings,
    )


class EnvironmentAgent:
    """Locked-down Environment Agent handle for a single job."""

    def __init__(self, job_id: str, *, settings: Settings | None = None) -> None:
        self.job_id = job_id
        self.settings = settings or get_settings()
        self.config_path = trusted_config_path(self.settings)
        self.config = load_trusted_config(self.settings)
        self.tools = HarnessTools(job_id, settings=self.settings)
        # Never treat submitted-repo docs as authority.
        refuse_repo_config_authority(self.config_path)

    def list_tools(self) -> list[str]:
        return self.tools.list_tools()

    def call_tool(self, name: str, **kwargs: Any) -> dict[str, Any]:
        return self.tools.call(name, **kwargs)

    def infer(self, messages: list[dict[str, Any]]) -> InferenceResult:
        return chat_completion(messages, job_id=self.job_id, settings=self.settings)
