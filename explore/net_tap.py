"""Plane 1 mitmproxy addon for bounded, job-scoped network observations.

The trusted TAP/mitmdump supervisor supplies this addon's job and sandbox
generation binding, canary plaintext, and evidence sink. The addon blocks
canary-bearing HTTP and DNS requests before forwarding and emits only redacted
records; firewall/TAP provisioning remains the supervisor's responsibility.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


class NetTapAddon:
    """Block known canary egress and emit redacted, generation-bound evidence."""

    def __init__(
        self,
        *,
        job_id: str,
        generation: int,
        canaries: Mapping[str, str],
        emit: Callable[[dict[str, Any]], None],
    ) -> None:
        if not job_id or type(generation) is not int or generation < 1:
            raise ValueError("valid job and sandbox generation are required")
        # Store only non-empty values; identifiers, not plaintext, enter events.
        self.job_id = job_id
        self.generation = generation
        self._canaries = {
            identifier: value.encode("utf-8")
            for identifier, value in canaries.items()
            if identifier and value
        }
        self._emit = emit
        self._sequence = 0
        self._lock = threading.Lock()

    def _matching_ids(self, payload: bytes) -> list[str]:
        """Find exact planted values without putting them in logs or events."""
        return [identifier for identifier, value in self._canaries.items() if value in payload]

    def _record(self, sensor: str, summary: str, *, count: int = 1) -> None:
        """Emit the shared bounded IPC shape; sequence allocation is thread-safe."""
        with self._lock:
            sequence = self._sequence
            self._sequence += 1
        observation_id = sha256(
            f"{self.job_id}:{self.generation}:{sensor}:{sequence}".encode()
        ).hexdigest()[:32]
        self._emit(
            {
                "job_id": self.job_id,
                "generation": self.generation,
                "sequence": sequence,
                "sensor": sensor,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "summary": summary,
                "counters": {"blocked": count},
                "observation_id": observation_id,
            }
        )

    def request(self, flow: Any) -> None:
        """Return a local 403 when request material contains a planted secret."""
        request = flow.request
        parts = [request.pretty_url.encode("utf-8", errors="replace")]
        parts.extend(
            f"{key}: {value}".encode("utf-8", errors="replace")
            for key, value in request.headers.items()
        )
        parts.append(request.raw_content or b"")
        matches = self._matching_ids(b"\n".join(parts))
        if not matches:
            return
        # mitmproxy is installed on the host that launches the addon, not in
        # the Plane 1 worker's ordinary test environment.
        from mitmproxy import http

        flow.response = http.Response.make(403, b"blocked by egress policy")
        self._record("canary_block", "blocked canary-bearing HTTP request", count=len(matches))

    def dns_request(self, flow: Any) -> None:
        """Return NXDOMAIN for a DNS question that embeds planted canary data."""
        question = flow.request.question
        if question is None:
            return
        payload = str(question.name).encode("utf-8", errors="replace").lower()
        matches = [
            identifier for identifier, value in self._canaries.items() if value.lower() in payload
        ]
        if not matches:
            return
        from mitmproxy import dns

        flow.response = flow.request.fail(dns.response_codes.NXDOMAIN)
        self._record("canary_block", "blocked canary-bearing DNS request", count=len(matches))
