"""Killhub pre-demo acceptance suite: black-box checks against a live deployment.

Runs real jobs through the public API (default https://killhub.pro) and asserts
what the product promises (PRODUCT.md / API.md / AGENTS.md):
plan → sandboxed execution → verifiable output → destroy, with honest
verification labels, cited SCA, containment evidence, active install checks,
canary secrecy and a durable receipt.

    KILLHUB_BASE_URL   target (default https://killhub.pro)
    KILLHUB_JOB_TIMEOUT  seconds to wait for all scenario jobs (default 2400)
    KILLHUB_SSH_HOST   ssh alias of the sandbox host (e.g. killhub-vx1); enables the
                       independent host cleanup check
    KILLHUB_RELEASE    1 = release validation: missing host evidence, no deployed
                       commit, missing operator evidence or skipped evidence checks
                       FAIL instead of skipping (see acceptance/README.md)
    KILLHUB_ARTIFACT_DIR  where the session artifact bundle is written
                       (default acceptance/artifacts/<UTC timestamp>)

Run:  explore/.venv/bin/python -m pytest acceptance            (everything)
      explore/.venv/bin/python -m pytest acceptance -m "not slow" (edge only)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from evidence import HostEvidence, Observation

BASE_URL = os.environ.get("KILLHUB_BASE_URL", "https://killhub.pro").rstrip("/")
JOB_TIMEOUT = float(os.environ.get("KILLHUB_JOB_TIMEOUT", "2400"))
TERMINAL = {"completed", "failed", "cancelled"}
RELEASE = os.environ.get("KILLHUB_RELEASE", "").strip().lower() in {"1", "true", "yes"}
REPO_ROOT = Path(__file__).resolve().parent.parent


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
        commit, source = deployed_commit(c)
        REGISTRY.notes["deployed_commit"] = commit
        REGISTRY.notes["deployed_commit_source"] = source
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


def submit(client: httpx.Client, url: str, label: str | None = None) -> str:
    """Create a job; ``label`` registers it for host cleanup verification + artifacts."""
    r = post_job(client, {"git_url": url})
    assert r.status_code in (200, 201), f"submit {url}: {r.status_code} {r.text[:300]}"
    job_id = r.json()["job_id"]
    if label:
        REGISTRY.register(label, job_id)
    return job_id


def snapshot(client: httpx.Client, job_id: str) -> dict[str, Any]:
    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200, f"snapshot {job_id}: {r.status_code}"
    snap = r.json()
    REGISTRY.observe(job_id, snap)
    return snap


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
        for name, jid in job_ids.items():
            REGISTRY.register(f"scenario:{name}", jid)
        return ScenarioRun(job_ids=job_ids, results=wait_terminal(client, job_ids))
    with ThreadPoolExecutor(max_workers=len(SCENARIOS)) as pool:
        ids = list(pool.map(lambda s: submit(client, s.url, f"scenario:{s.name}"), SCENARIOS))
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


# --- session registry, release gating and artifact bundle ---------------------------------


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunRegistry:
    """Everything the session saw, retained as acceptance evidence.

    Every job any test creates (scenario, cancel, cancel-boundary, SSE) is registered
    so the host cleanup check covers all of them, not only the golden scenarios.
    """

    started_at: str = field(default_factory=_utc)
    jobs: dict[str, str] = field(default_factory=dict)  # label -> job_id
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)  # job_id -> latest
    observations: list[Observation] = field(default_factory=list)
    host_evidence: HostEvidence | None = None
    outcomes: dict[str, str] = field(default_factory=dict)  # nodeid -> outcome
    release_gaps: list[str] = field(default_factory=list)
    notes: dict[str, Any] = field(default_factory=dict)

    def register(self, label: str, job_id: str) -> None:
        self.jobs[label] = job_id

    def observe(self, job_id: str, snap: dict[str, Any]) -> None:
        self.snapshots[job_id] = snap
        self.observations.append(
            Observation(
                job_id=job_id,
                status=str(snap.get("status")),
                has_receipt=bool(snap.get("receipt")),
                at=_utc(),
            )
        )

    @property
    def job_ids(self) -> list[str]:
        return sorted(set(self.jobs.values()))


REGISTRY = RunRegistry()


def evidence_unavailable(reason: str) -> None:
    """Required evidence could not be gathered.

    Release validation (``KILLHUB_RELEASE=1``) fails; a developer run skips. Either
    way the gap is recorded in the artifact bundle so a green dev run is never
    mistaken for a release pass.
    """
    REGISTRY.release_gaps.append(reason)
    if RELEASE:
        pytest.fail(f"release validation incomplete: {reason}", pytrace=False)
    pytest.skip(f"{reason} (dev run; fails under KILLHUB_RELEASE=1)")


def deployed_commit(client: httpx.Client) -> tuple[str | None, str]:
    """Best available deployed commit and its source. Never guesses from the local checkout."""
    env = os.environ.get("KILLHUB_DEPLOYED_COMMIT", "").strip()
    if env:
        return env, "env:KILLHUB_DEPLOYED_COMMIT"
    try:
        body = client.get("/health").json()
        for key in ("commit", "git_sha", "version"):
            if isinstance(body, dict) and body.get(key):
                return str(body[key]), f"health:{key}"
    except (httpx.HTTPError, ValueError):
        pass
    host, directory = os.environ.get("KILLHUB_SSH_HOST"), os.environ.get("KILLHUB_DEPLOY_DIR")
    if host and directory:
        try:
            out = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", host, "git", "-C", directory, "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip(), "ssh:git rev-parse HEAD"
        except (OSError, subprocess.SubprocessError):
            pass
    return None, "unavailable"


def _local_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "release: evidence that must exist for release validation (KILLHUB_RELEASE=1)"
    )
    config.addinivalue_line("markers", "host_cleanup: runs last, after every job has finished")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Host cleanup must run after every test that creates a job."""
    items.sort(key=lambda it: it.get_closest_marker("host_cleanup") is not None)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        REGISTRY.outcomes[report.nodeid] = report.outcome


def _job_artifact(job_id: str) -> dict[str, Any]:
    snap = REGISTRY.snapshots.get(job_id) or {}
    receipt = snap.get("receipt") or {}
    return {
        "job_id": job_id,
        "status": snap.get("status"),
        "git_url": snap.get("git_url"),
        "resolved_commit": snap.get("resolved_commit"),
        "sandbox_id": snap.get("sandbox_id"),
        "cleanup": snap.get("cleanup"),
        "destroyed_at": snap.get("destroyed_at"),
        "cancel_requested_at": snap.get("cancel_requested_at"),
        "sandbox_generations": (receipt.get("dossier") or {}).get("sandbox_generations"),
        "receipt_present": bool(receipt),
    }


def release_validation(exitstatus: int) -> dict[str, Any]:
    reasons = list(dict.fromkeys(REGISTRY.release_gaps))
    if exitstatus != 0:
        reasons.append(f"pytest exit status {exitstatus}")
    host = REGISTRY.host_evidence
    if host is None:
        reasons.append("host cleanup evidence was not collected")
    elif not host.ok:
        reasons.append(f"host cleanup evidence failed: {host.error or host.retained}")
    if not REGISTRY.notes.get("deployed_commit"):
        reasons.append("deployed commit unknown")
    skipped = sorted(n for n, o in REGISTRY.outcomes.items() if o == "skipped")
    if RELEASE and skipped:
        reasons.append(f"skipped checks: {skipped}")
    return {"release_mode": RELEASE, "valid": RELEASE and not reasons, "reasons": reasons}


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write the evidence bundle: commit, job ids, receipts, host cleanup evidence."""
    if not REGISTRY.jobs and not RELEASE:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(
        os.environ.get("KILLHUB_ARTIFACT_DIR") or Path(__file__).parent / "artifacts" / stamp
    )
    try:
        (root / "receipts").mkdir(parents=True, exist_ok=True)
        for jid in REGISTRY.job_ids:
            receipt = (REGISTRY.snapshots.get(jid) or {}).get("receipt")
            if receipt:
                (root / "receipts" / f"{jid}.json").write_text(json.dumps(receipt, indent=2))
        bundle = {
            "schema_version": 1,
            "started_at": REGISTRY.started_at,
            "finished_at": _utc(),
            "base_url": BASE_URL,
            "deployed_commit": REGISTRY.notes.get("deployed_commit"),
            "deployed_commit_source": REGISTRY.notes.get("deployed_commit_source"),
            "local_checkout_commit": _local_commit(),
            "jobs": {label: _job_artifact(jid) for label, jid in sorted(REGISTRY.jobs.items())},
            "host_cleanup": REGISTRY.host_evidence.to_json() if REGISTRY.host_evidence else None,
            "observed_transitions": [vars(o) for o in REGISTRY.observations],
            "operator_evidence": REGISTRY.notes.get("operator_evidence"),
            "test_outcomes": dict(sorted(REGISTRY.outcomes.items())),
            "release_validation": release_validation(int(exitstatus)),
        }
        (root / "results.json").write_text(json.dumps(bundle, indent=2, default=str))
        print(f"\nacceptance artifacts: {root}")
    except OSError as exc:  # evidence retention must not mask the test verdict
        print(f"\nacceptance artifacts NOT written: {exc}")
