"""Plane 1 inference smoke check for an authenticated, trusted VX1 guest.

The management transport supplies the job and generation. The guest receives
a short-lived bearer and can request only a fixed host-owned check. Provider
credentials, output, and upstream errors stay on Plane 1.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from typing import Any

import httpx

from agent import AgentError, resolve_inference_model
from config import Settings
from ledger import Ledger
from models import Job

_VULTR_BASE = "https://api.vultrinference.com/v1"
_GRANT_TTL_SECONDS = 300
_MAX_TURNS = 12
_MAX_TOKENS = 60_000
_MAX_COMPLETION_TOKENS = 32
# The fixed short prompt has generous room for provider chat formatting.
_CALL_TOKEN_BOUND = 1024


class InferenceSmokeError(Exception):
    """Transport-independent, guest-safe error contract."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class InferenceSmokeSession:
    """Bind a trusted smoke run to one job generation and its absolute expiry.

    The host management transport creates one session per generation and reuses
    it for retries, so ambiguous provider failures retain their reservation.
    """

    def __init__(self, *, job_id: str, generation: int, ledger: Ledger, settings: Settings) -> None:
        self.job_id = job_id
        self.generation = generation
        self._ledger = ledger
        self._settings = settings
        self._bearer = secrets.token_urlsafe(32)
        self._grant_expires = monotonic() + _GRANT_TTL_SECONDS
        self._lock = Lock()
        self._turns = 0
        self._unconfirmed_tokens = 0

    def bearer(self) -> str:
        """Pass the dummy bearer only to the trusted guest bootstrap."""
        return self._bearer

    def _live_job(self) -> Job:
        """Recheck the ledger so cancellation or replacement invalidates a grant."""
        job = self._ledger.get_job(self.job_id)
        if (
            monotonic() >= self._grant_expires
            or job is None
            or job.current_sandbox_generation != self.generation
            or not job.sandbox_id
            or job.status not in {"installing", "verifying"}
            or job.cancel_requested_at is not None
            or job.destroyed_at is not None
            or job.cleanup.status != "pending"
            or datetime.fromisoformat(job.expires_at.replace("Z", "+00:00"))
            <= datetime.now(timezone.utc)
        ):
            raise InferenceSmokeError(403, "inference_session_inactive")
        return job

    def run(
        self,
        *,
        job_id: str,
        generation: int,
        authorization: str,
        client: httpx.Client | None = None,
    ) -> dict[str, int]:
        """Perform one fixed check and return only accounted usage."""
        if (
            job_id != self.job_id
            or generation != self.generation
            or not secrets.compare_digest(
                authorization.encode("utf-8"), f"Bearer {self._bearer}".encode("ascii")
            )
        ):
            raise InferenceSmokeError(403, "inference_session_denied")

        # Serialize both reservation and accounting for this live management session.
        with self._lock:
            job = self._live_job()
            usage = job.inference_usage or {}
            smoke = (usage.get("by_role") or {}).get("guest_smoke", {})
            turns = max(int(smoke.get("calls") or 0), self._turns)
            known_tokens = int(smoke.get("total_tokens") or 0)
            remaining = _MAX_TOKENS - known_tokens - self._unconfirmed_tokens
            job_budget = self._settings.inference_budget_tokens_per_job
            if job_budget > 0:
                job_remaining = job_budget - int(usage.get("total_tokens") or 0)
                remaining = min(remaining, job_remaining - self._unconfirmed_tokens)
            if turns >= _MAX_TURNS or remaining < _CALL_TOKEN_BOUND:
                raise InferenceSmokeError(429, "kill_switch_layer1")

            model, key = self._provider()
            self._turns = turns + 1
            # A timeout or unusable usage response may still have consumed tokens.
            self._unconfirmed_tokens += _CALL_TOKEN_BOUND
            if client is None:
                with httpx.Client(timeout=15.0, trust_env=False) as outbound:
                    prompt_tokens, completion_tokens = self._call(outbound, model, key)
            else:
                prompt_tokens, completion_tokens = self._call(client, model, key)
            total = prompt_tokens + completion_tokens

            self._live_job()
            try:
                self._ledger.add_inference_usage(
                    self.job_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total,
                    budget_tokens=job_budget,
                    role="guest_smoke",
                )
            except (KeyError, Ledger.WriterFrozenError) as exc:
                raise InferenceSmokeError(403, "inference_session_inactive") from exc
            self._unconfirmed_tokens -= _CALL_TOKEN_BOUND
            return {"turns": self._turns, "total_tokens": known_tokens + total}

    def _provider(self) -> tuple[str, str]:
        """Use the exact approved endpoint and host-owned model configuration."""
        key = self._settings.vultr_inference_api_key.strip()
        if not key or self._settings.vultr_inference_base_url.rstrip("/") != _VULTR_BASE:
            raise InferenceSmokeError(503, "inference_not_configured")
        try:
            return resolve_inference_model(self._settings), key
        except AgentError as exc:
            raise InferenceSmokeError(503, "inference_not_configured") from exc

    @staticmethod
    def _call(client: httpx.Client, model: str, key: str) -> tuple[int, int]:
        """Replace guest auth with the host key and project only numeric usage."""
        try:
            response = client.post(
                f"{_VULTR_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Reply with OK."}],
                    "max_completion_tokens": _MAX_COMPLETION_TOKENS,
                    "temperature": 0,
                },
                follow_redirects=False,
            )
            response.raise_for_status()
            data = response.json()
            assistant_content = data["choices"][0]["message"]["content"]
            if not isinstance(assistant_content, str) or not assistant_content.strip():
                raise ValueError("empty provider completion")
            raw_usage: Any = data["usage"]
            prompt = raw_usage["prompt_tokens"]
            completion = raw_usage["completion_tokens"]
        except (httpx.HTTPError, IndexError, TypeError, ValueError, KeyError):
            # Public transport errors may never carry provider bodies or credentials.
            raise InferenceSmokeError(502, "inference_check_failed") from None
        if (
            type(prompt) is not int
            or type(completion) is not int
            or prompt <= 0
            or not 0 < completion <= _MAX_COMPLETION_TOKENS
            or raw_usage.get("total_tokens", prompt + completion) != prompt + completion
            or prompt + completion > _CALL_TOKEN_BOUND
        ):
            raise InferenceSmokeError(502, "inference_usage_invalid")
        return prompt, completion
