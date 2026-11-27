"""Killhub pre-demo acceptance suite — black-box checks against a live deployment.

Runs real jobs through the public API (default https://killhub.pro) and asserts
what the product promises (PRODUCT.md / API.md / AGENTS.md):
plan → sandboxed execution → verifiable output → destroy, with honest
verification labels, cited SCA, containment evidence, active install checks,
canary secrecy and a durable receipt.

    KILLHUB_BASE_URL   target (default https://killhub.pro)
    KILLHUB_JOB_TIMEOUT  seconds to wait for all scenario jobs (default 2400)
    KILLHUB_SSH_HOST   optional ssh alias of the sandbox host (e.g. killhub-vx1);
                       enables the "no leaked sandboxes" host check

Run:  explore/.venv/bin/python -m pytest acceptance            (everything)
      explore/.venv/bin/python -m pytest acceptance -m "not slow" (edge only)
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

BASE_URL = os.environ.get("KILLHUB_BASE_URL", "https://killhub.pro").rstrip("/")
JOB_TIMEOUT = float(os.environ.get("KILLHUB_JOB_TIMEOUT", "2400"))
TERMINAL = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class Scenario:
    """One demo-relevant repo and what Killhub must conclude about it."""

    name: str
    url: str
    status: str  # expected terminal status
    kind: str | None  # expected verification.kind
    readiness: bool | None = None  # expected readiness.passed (None = don't care)
    readiness_probe: str | None = None  # prefix of readiness.probe
    sca_packages: tuple[str, ...] = ()  # package-name prefixes that must be flagged
    no_sca: bool = False  # control: no SCA advisories allowed
    finding_codes: tuple[str, ...] = ()  # activity/security finding codes required
    forbidden_codes: tuple[str, ...] = ()  # codes that must NOT appear
    hard_fail: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "webapp",
        "https://github.com/heroku/nodejs-getting-started",
        "completed",
        "original_application",
        readiness=True,
        readiness_probe="http",
    ),
    Scenario(
        "node_mcp_filesystem",
        "https://github.com/modelcontextprotocol/servers",
        "completed",
        "original_application",
        readiness=True,
        readiness_probe="mcp_handshake",
        forbidden_codes=("mcp_tool_poisoning", "canary_exfiltration"),
    ),
    Scenario(
        "python_mcp_vultr",
        "https://github.com/vultr/vultr-mcp",
        "completed",
        "original_application",
        readiness=True,
        readiness_probe="mcp_handshake",
        forbidden_codes=("mcp_tool_poisoning", "canary_exfiltration", "persistence_write"),
        extra={"min_tools": 50, "lockfile_scanned": True},
    ),
    Scenario(
        "setup_failed",
        "https://github.com/octocat/Hello-World",
        "failed",
        "setup_failed",
    ),
    Scenario(
        "sca_npm_affected",
        "https://github.com/mokafari/killhub-sca-npm-affected-20261127",
        "completed",
        None,
        sca_packages=("minimist",),
    ),
    Scenario(
        "sca_npm_control",
        "https://github.com/mokafari/killhub-sca-npm-control-20261127",
        "completed",
        None,
        no_sca=True,
    ),
    Scenario(
        "sca_python_affected",
        "https://github.com/mokafari/killhub-sca-python-affected-20261127",
        "completed",
        None,
        sca_packages=("PyYAML",),
    ),
    Scenario(
        "leaky_install",
        "https://github.com/mokafari/killhub-leaky-install-20261127",
        "failed",
        "original_application",
        readiness=True,
        finding_codes=("canary_exfiltration", "persistence_write"),
        hard_fail=True,
    ),
)


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=30.0, follow_redirects=False) as c:
        yield c


def post_job(client: httpx.Client, body: dict[str, Any], *, budget: float = 900) -> httpx.Response:
    """POST /api/jobs, waiting out admission back-pressure (D40).

    The public API allows 10 creates per IP per minute (429 rate_limited) and a
    bounded queue (503 queue_full). Those are correct responses, not failures:
    back off and retry until ``budget`` seconds are spent.
    """
    deadline = time.monotonic() + budget
    delay = 10.0
    while True:
        r = client.post("/api/jobs", json=body)
        code = ""
        if r.status_code in (429, 503):
            try:
                code = r.json().get("code", "")
            except ValueError:
                code = ""
            assert code in {
                "rate_limited",
                "queue_full",
                "inference_budget",
                "admission_unavailable",
            }, (
                r.status_code,
                r.text[:200],
            )
        if r.status_code not in (429, 503) or code not in {"rate_limited", "queue_full"}:
            return r
        if time.monotonic() + delay > deadline:
            return r
        time.sleep(float(r.headers.get("retry-after") or delay))
        delay = min(delay * 1.5, 60.0)


def submit(client: httpx.Client, url: str) -> str:
    r = post_job(client, {"github_url": url})
    assert r.status_code in (200, 201), f"submit {url}: {r.status_code} {r.text[:300]}"
    return r.json()["job_id"]


def snapshot(client: httpx.Client, job_id: str) -> dict[str, Any]:
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200, f"snapshot {job_id}: {r.status_code}"
    return r.json()


def wait_terminal(
    client: httpx.Client, job_ids: dict[str, str], timeout: float = JOB_TIMEOUT
) -> dict[str, dict[str, Any]]:
    """Poll until every job is terminal; return final snapshots (stuck jobs fail loudly)."""
    deadline = time.monotonic() + timeout
    done: dict[str, dict[str, Any]] = {}
    while len(done) < len(job_ids) and time.monotonic() < deadline:
        for name, jid in job_ids.items():
            if name in done:
                continue
            try:
                snap = snapshot(client, jid)
            except (httpx.HTTPError, AssertionError):
                continue
            if snap.get("status") in TERMINAL:
                done[name] = snap
        if len(done) < len(job_ids):
            time.sleep(15)
    missing = {n: job_ids[n] for n in job_ids if n not in done}
    assert not missing, f"jobs not terminal after {timeout}s: {missing}"
    return done


@dataclass
class ScenarioRun:
    job_ids: dict[str, str]
    results: dict[str, dict[str, Any]]


@pytest.fixture(scope="session")
def scenario_run(client: httpx.Client) -> ScenarioRun:
    """Submit every scenario at once (also a concurrency test), wait for all.

    KILLHUB_REUSE_JOBS='{"webapp": "<job id>", ...}' re-checks finished jobs
    instead of submitting new ones (fast re-evaluation after a test fix).
    """
    reuse = os.environ.get("KILLHUB_REUSE_JOBS")
    if reuse:
        job_ids = json.loads(reuse)
        assert set(job_ids) == {s.name for s in SCENARIOS}, sorted(job_ids)
        return ScenarioRun(job_ids=job_ids, results=wait_terminal(client, job_ids))
    with ThreadPoolExecutor(max_workers=len(SCENARIOS)) as pool:
        ids = list(pool.map(lambda s: submit(client, s.url), SCENARIOS))
    job_ids = {s.name: jid for s, jid in zip(SCENARIOS, ids, strict=True)}
    print("\nscenario jobs:", json.dumps(job_ids))
    return ScenarioRun(job_ids=job_ids, results=wait_terminal(client, job_ids))


def findings(snap: dict[str, Any]) -> list[dict[str, Any]]:
    return list((snap.get("vuln_report") or {}).get("findings") or [])


def finding_code(f: dict[str, Any]) -> str | None:
    """Finding code per DATABASE.md: ``detail.code`` (fallback: legacy top-level ``code``)."""
    code = (f.get("detail") or {}).get("code") or f.get("code")
    return str(code) if code else None


def finding_codes(snap: dict[str, Any]) -> set[str]:
    return {c for f in findings(snap) if (c := finding_code(f))}
