"""Adaptive discovery + repair through the Environment Agent (D85, D8, D47, D54, D10).

Inference is faked at ``agent.chat_completion`` (the Vultr boundary); budget
accounting still runs through the real ``record_inference_usage``.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from profile import validate_profile
from typing import Any

import pytest

import agent as agent_mod
from agent import (
    AgentError,
    EnvironmentAgent,
    InferenceResult,
    extract_json_object,
    record_inference_usage,
)
from config import get_settings
from discover import TrustedFacts, discover_runtime_profile
from harness import ExecResult
from install import InstallError, provision_and_go_offline
from jobs import get_ledger, reset_ledger_for_tests
from plan_llm import PlanLLMError, deadline_exceeded, sanitize_profile
from service import create_job
from verify import verify_readiness

SHA = "b" * 40
GO_URL = "https://github.com/example/goserver"
ROOT = "/tmp/killhub/repo"

GO_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "webapp",
    "runtime": "go",
    "workdir": ROOT,
    # Attacker/model-chosen trusted facts must be overwritten.
    "source": {"type": "git", "url": "https://evil.example/x", "commit": "f" * 40},
    "oci_image": "evil/image:latest",
    "services": [],
    "packages": ["golang-go"],
    "install_commands": [
        {
            "argv": ["go", "build", "-o", "server", "."],
            "timeout_seconds": 600,
            "env": {"CGO_ENABLED": "0"},
        }
    ],
    "run_commands": [{"argv": ["./server"], "timeout_seconds": 60}],
    "processes": [
        {
            "name": "web",
            "command": {"argv": ["./server"], "timeout_seconds": 3600, "env": {"PORT": "8080"}},
            "supervise": "restart",
            "ready_after_seconds": 2,
        }
    ],
    "ports": [8080],
    "probes": [
        {
            "name": "root",
            "type": "http",
            "url": "http://127.0.0.1:8080/",
            "accept": [200],
            "timeout_seconds": 5,
        }
    ],
    "summary": "Go HTTP server from go.mod + Procfile",
}

GO_INSPECT = (
    "---TREE---\n./go.mod\n./main.go\n./Procfile\n"
    "---PACKAGE_JSON---\n---PYPROJECT---\n---REQUIREMENTS---\n---README---\nA go server\n"
    "---MCP_FS---\n---MANIFESTS---\n=== go.mod ===\nmodule example.com/goserver\ngo 1.22\n"
    "=== Procfile ===\nweb: ./server\n"
)


class FakeLLM:
    """Queue-driven stand-in for Vultr chat completions (keeps real budget accounting)."""

    def __init__(self) -> None:
        self.replies: list[Any] = []
        self.calls: list[list[dict[str, Any]]] = []

    def __call__(
        self,
        messages: list[dict[str, Any]],
        *,
        job_id: str | None = None,
        settings: Any = None,
        **_kw: Any,
    ) -> InferenceResult:
        self.calls.append(messages)
        if not self.replies:
            raise AgentError("no scripted reply", code="inference_transport")
        reply = self.replies.pop(0)
        content = reply if isinstance(reply, str) else json.dumps(reply)
        result = InferenceResult(
            model="test-model",
            content=content,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            raw={},
        )
        if job_id is not None:
            record_inference_usage(job_id, result, settings=settings)
        return result


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("MSB_DEFAULT_IMAGE", "debian")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "3")
    monkeypatch.setenv("PROFILE_STORAGE", str(tmp_path / "profiles"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    monkeypatch.setattr("screenshots.ensure_playwright_tooling", lambda *a, **k: {})
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("VULTR_INFERENCE_MODEL", "test-model")
    get_settings.cache_clear()
    fake = FakeLLM()
    monkeypatch.setattr(agent_mod, "chat_completion", fake)
    return fake


def _facts(**over: str) -> TrustedFacts:
    base = {"github_url": GO_URL, "commit": SHA, "ref": "HEAD", "oci_image": "debian"}
    base.update(over)
    return TrustedFacts(**base)


def _events(job_id: str, typ: str) -> list[Any]:
    return [e for e in get_ledger().list_events(job_id) if e.type == typ]


# ---------------------------------------------------------------------------
# Sanitizer: model output is untrusted
# ---------------------------------------------------------------------------


def test_sanitize_pins_trusted_facts_and_validates() -> None:
    profile = sanitize_profile(GO_PROFILE, facts=_facts(), settings=get_settings())
    assert profile["source"] == {"type": "git", "url": GO_URL, "commit": SHA, "ref": "HEAD"}
    assert profile["oci_image"] == "debian"
    assert profile["verification_target"] == "original_application"
    assert profile["install_commands"][0]["cwd"] == ROOT
    validate_profile(profile, phase="runtime")


def test_sanitize_resolves_relative_cwd_under_checkout() -> None:
    raw = copy.deepcopy(GO_PROFILE)
    raw["install_commands"][0]["cwd"] = "cmd/server"
    profile = sanitize_profile(raw, facts=_facts(), settings=get_settings())
    assert profile["install_commands"][0]["cwd"] == f"{ROOT}/cmd/server"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda p: p["probes"][0].update(url="http://example.com/"), "plan_forbidden"),
        (lambda p: p["install_commands"][0].update(cwd="/etc"), "plan_forbidden"),
        (lambda p: p["install_commands"][0].update(cwd="../../.."), "plan_forbidden"),
        (
            lambda p: p["install_commands"].__setitem__(
                0, {"shell": "echo $VULTR_API_KEY", "timeout_seconds": 5}
            ),
            "plan_forbidden",
        ),
        (lambda p: p["install_commands"][0]["env"].update(VULTR_API_KEY="x"), "plan_forbidden"),
        (
            lambda p: p["run_commands"][0].update(argv=["curl", "https://killhub.pro/x"]),
            "plan_forbidden",
        ),
        (lambda p: p["probes"][0].update(type="tcp"), "plan_unsupported"),
        (lambda p: p.update(ports=[70000]), "plan_rejected"),
        (lambda p: p.update(intent="bootstrap"), "plan_intent"),
        (lambda p: p.update(packages=["ok; rm -rf /"]), "plan_rejected"),
        (lambda p: p.pop("probes"), "plan_profile_invalid"),
        (
            lambda p: p["run_commands"][0].update(argv=["npx", "-y", "some-pkg"]),
            "plan_unpinned_registry_launch",
        ),
    ],
)
def test_sanitize_rejects_unsafe_or_invalid_profiles(mutate: Any, code: str) -> None:
    raw = copy.deepcopy(GO_PROFILE)
    mutate(raw)
    with pytest.raises(PlanLLMError) as err:
        sanitize_profile(raw, facts=_facts(), settings=get_settings())
    assert err.value.code == code


def test_sanitize_denies_configured_control_plane_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTROL_PLANE_DENY_HOSTS", "cp.internal.example")
    get_settings.cache_clear()
    raw = copy.deepcopy(GO_PROFILE)
    raw["install_commands"][0] = {
        "shell": "wget http://cp.internal.example/",
        "timeout_seconds": 30,
    }
    with pytest.raises(PlanLLMError) as err:
        sanitize_profile(raw, facts=_facts(), settings=get_settings())
    assert err.value.code == "plan_forbidden"


def test_demo_intent_is_labeled_generated_with_original_failure() -> None:
    raw = copy.deepcopy(GO_PROFILE)
    raw["intent"] = "demo"
    profile = sanitize_profile(
        raw,
        facts=_facts(),
        settings=get_settings(),
        original_failure={"step": "install", "summary": "go build failed"},
    )
    assert profile["verification_target"] == "generated_demo"
    assert profile["original_failure"] == {"step": "install", "summary": "go build failed"}


def test_non_demo_never_claims_a_generated_label_or_failure() -> None:
    raw = copy.deepcopy(GO_PROFILE)
    raw["verification_target"] = "generated_demo"
    raw["original_failure"] = {"step": "x", "summary": "y"}
    profile = sanitize_profile(raw, facts=_facts(), settings=get_settings())
    assert profile["verification_target"] == "original_application"
    assert "original_failure" not in profile


def test_verify_phase_locks_install_side_fields() -> None:
    current = sanitize_profile(GO_PROFILE, facts=_facts(), settings=get_settings())
    raw = copy.deepcopy(GO_PROFILE)
    raw["intent"] = "demo"
    raw["packages"] = ["evil-package"]
    raw["install_commands"] = [{"shell": "true", "timeout_seconds": 5}]
    raw["probes"][0]["url"] = "http://127.0.0.1:9090/"
    raw["ports"] = [9090]
    revised = sanitize_profile(
        raw,
        facts=_facts(),
        settings=get_settings(),
        current=current,
        locked=("packages", "install_commands", "intent", "verification_target", "runtime"),
    )
    assert revised["intent"] == "webapp"
    assert revised["packages"] == current["packages"]
    assert revised["install_commands"] == current["install_commands"]
    assert revised["verification_target"] == "original_application"
    assert revised["ports"] == [9090]
    assert revised["probes"][0]["url"].endswith(":9090/")


def test_extract_json_object_tolerates_fences_and_prose() -> None:
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    assert extract_json_object("no json") is None
    assert extract_json_object("[1, 2]") is None


def test_deadline_exceeded() -> None:
    assert deadline_exceeded("2000-01-01T00:00:00Z") is True
    assert deadline_exceeded("2999-01-01T00:00:00Z") is False
    assert deadline_exceeded(None) is False


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class _FakeExec:
    def __init__(self, *, commit: str, inspect_stdout: str) -> None:
        self.commit = commit
        self.inspect_stdout = inspect_stdout

    def __call__(
        self,
        environment_id: str,
        cmd: Sequence[str] | str,
        **_kw: Any,
    ) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "command -v git" in joined:
            return ExecResult("/usr/bin/git\n", "", 0)
        if "git rev-parse HEAD" in joined:
            return ExecResult(f"{self.commit}\n", "", 0)
        if "---TREE---" in joined:
            return ExecResult(self.inspect_stdout, "", 0)
        return ExecResult("", "", 0)


@pytest.fixture
def sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "discover.create_environment",
        lambda *a, **k: type(
            "G",
            (),
            {
                "environment_id": "env-plan",
                "generation": 1,
                "state": "running",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )(),
    )
    monkeypatch.setattr("discover.wait_until_ready", lambda *a, **k: None)
    monkeypatch.setattr("discover.destroy_job_environment", lambda *a, **k: None)


def _discover(url: str, inspect_stdout: str, *, commit: str = SHA) -> Any:
    job = create_job(url)
    result = discover_runtime_profile(
        job.job_id,
        exec_fn=_FakeExec(commit=commit, inspect_stdout=inspect_stdout),
        create=True,
        destroy_on_failure=False,
    )
    return job, result


def test_unfamiliar_go_repo_gets_a_suitable_llm_plan(llm: FakeLLM, sandbox: None) -> None:
    llm.replies.append(
        {
            "profile": GO_PROFILE,
            "rationale": "go.mod + Procfile 'web: ./server' => build with go, run ./server",
            "evidence": ["go.mod", "Procfile web"],
        }
    )
    job, result = _discover(GO_URL, GO_INSPECT)

    profile = result.profile
    assert profile["intent"] == "webapp"
    assert profile["runtime"] == "go"
    assert profile["ports"] == [8080]
    assert profile["probes"][0]["url"] == "http://127.0.0.1:8080/"
    assert profile["verification_target"] == "original_application"
    # Resolved commit preserved; model could not redirect source or image.
    assert result.resolved_commit == SHA
    assert profile["source"]["commit"] == SHA
    assert profile["source"]["url"] == GO_URL
    assert profile["oci_image"] == "debian"
    validate_profile(profile, phase="runtime")

    # The model saw the inspected evidence as delimited untrusted data.
    assert len(llm.calls) == 1
    user = llm.calls[0][1]["content"]
    assert "module example.com/goserver" in user
    assert "UNTRUSTED CHECKOUT INSPECTION BEGIN" in user
    assert "Procfile" in user

    refreshed = get_ledger().get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.resolved_commit == SHA
    assert refreshed.inference_model == "test-model"
    assert refreshed.inference_usage and refreshed.inference_usage["total_tokens"] == 150
    revs = get_ledger().list_profile_revisions(job.job_id)
    assert [r.phase for r in revs] == ["bootstrap", "runtime"]
    assert revs[1].profile["runtime"] == "go"
    assert any(
        e.payload.get("planner") == "llm" and "go.mod" in e.payload.get("rationale", "")
        for e in _events(job.job_id, "log")
    )


def test_discovery_falls_back_to_heuristics_without_inference(sandbox: None) -> None:
    # No key (conftest strips it): honest heuristic demo, labeled generated_demo (D54).
    job, result = _discover(GO_URL, GO_INSPECT)
    assert result.profile["intent"] == "demo"
    assert result.profile["verification_target"] == "generated_demo"
    assert result.profile["original_failure"]["step"] == "discover"
    skipped = [
        e
        for e in _events(job.job_id, "span")
        if e.message == "plan_llm_discover" and e.payload["status"] == "skipped"
    ]
    assert skipped and skipped[0].payload["reason"] == "inference_unavailable"


def test_rejected_llm_reply_falls_back_to_heuristics(llm: FakeLLM, sandbox: None) -> None:
    bad = copy.deepcopy(GO_PROFILE)
    bad["probes"][0]["url"] = "http://example.com/"
    llm.replies.append({"profile": bad, "rationale": "x"})
    job, result = _discover(GO_URL, GO_INSPECT)
    assert result.profile["intent"] == "demo"
    assert result.profile["verification_target"] == "generated_demo"
    rejected = [
        e
        for e in _events(job.job_id, "span")
        if e.message == "plan_llm_discover" and e.payload["status"] == "rejected"
    ]
    assert rejected and rejected[0].payload["reason"] == "plan_forbidden"


def test_garbage_llm_reply_falls_back(llm: FakeLLM, sandbox: None) -> None:
    llm.replies.append("I cannot help with that")
    _, result = _discover(GO_URL, GO_INSPECT)
    assert result.profile["intent"] == "demo"


def test_llm_demo_cannot_displace_a_heuristic_original_fit(llm: FakeLLM, sandbox: None) -> None:
    demo = copy.deepcopy(GO_PROFILE)
    demo["intent"] = "demo"
    llm.replies.append({"profile": demo, "rationale": "just serve static files"})
    express = (
        "---TREE---\n./package.json\n./index.js\n"
        '---PACKAGE_JSON---\n{"name":"web","dependencies":{"express":"4"}}\n'
        "---README---\nhi\n"
    )
    _, result = _discover("https://github.com/example/getting-started-app", express)
    assert result.profile["intent"] == "webapp"
    assert result.profile["verification_target"] == "original_application"


def test_pinned_fixture_stays_deterministic_without_inference(llm: FakeLLM, sandbox: None) -> None:
    from fixtures import require_fixture

    web = require_fixture("webapp_success")
    _, result = _discover(
        web["github_url"],
        "---TREE---\n./package.json\n"
        '---PACKAGE_JSON---\n{"dependencies":{"express":"4"}}\n---README---\nx\n',
        commit=web["commit"],
    )
    assert llm.calls == []
    assert result.profile["intent"] == "webapp"


def test_discovery_respects_inference_budget(
    llm: FakeLLM, sandbox: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INFERENCE_BUDGET_TOKENS_PER_JOB", "100")
    get_settings.cache_clear()
    job = create_job(GO_URL)
    get_ledger().update_job_fields(job.job_id, inference_usage={"total_tokens": 100})
    llm.replies.append({"profile": GO_PROFILE, "rationale": "x"})
    result = discover_runtime_profile(
        job.job_id,
        exec_fn=_FakeExec(commit=SHA, inspect_stdout=GO_INSPECT),
        create=True,
        destroy_on_failure=False,
    )
    assert llm.calls == []
    assert result.profile["intent"] == "demo"


def test_agent_tracks_budget_and_fails_closed(
    llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INFERENCE_BUDGET_TOKENS_PER_JOB", "200")
    get_settings.cache_clear()
    job = create_job(GO_URL)
    agent = EnvironmentAgent(job.job_id, settings=get_settings())
    assert agent.inference_available() == (True, "ok")
    llm.replies.append({"profile": {}})
    agent.infer_json(system="s", user="u")
    after = get_ledger().get_job(job.job_id)
    assert after is not None and after.inference_usage["total_tokens"] == 150
    assert agent.inference_available() == (True, "ok")
    get_ledger().update_job_fields(job.job_id, inference_usage={"total_tokens": 200})
    assert agent.inference_available() == (False, "inference_budget")


# ---------------------------------------------------------------------------
# Install repair
# ---------------------------------------------------------------------------

NODE_PROFILE: dict[str, Any] = {
    "schema_version": "1",
    "intent": "webapp",
    "oci_image": "debian",
    "os_image": "linux",
    "runtime": "node",
    "workdir": ROOT,
    "source": {"type": "git", "url": GO_URL, "commit": SHA, "ref": "HEAD"},
    "services": [],
    "packages": [],
    "install_commands": [{"argv": ["npm", "install"], "cwd": ROOT, "timeout_seconds": 600}],
    "run_commands": [{"argv": ["npm", "start"], "cwd": ROOT, "timeout_seconds": 60}],
    "processes": [
        {
            "name": "web",
            "command": {"argv": ["npm", "start"], "cwd": ROOT, "timeout_seconds": 3600},
            "supervise": "restart",
            "ready_after_seconds": 2,
        }
    ],
    "ports": [5000],
    "probes": [
        {
            "name": "root",
            "type": "http",
            "url": "http://127.0.0.1:5000/",
            "accept": [200],
            "timeout_seconds": 5,
        }
    ],
    "summary": "node webapp",
    "verification_target": "original_application",
}


def _seed_install_job() -> str:
    job = create_job(GO_URL)
    ledger = get_ledger()
    ledger.append_sandbox_generation(
        job.job_id,
        environment_id="env-install",
        image="debian",
        expires_at=job.expires_at,
        state="running",
    )
    ledger.update_job_fields(job.job_id, resolved_commit=SHA)
    ledger.append_profile_revision(
        job.job_id,
        phase="runtime",
        schema_version="1",
        profile=NODE_PROFILE,
        storage_path=None,
    )
    return job.job_id


class _Step:
    def __init__(self, name: str, ok: bool, detail: str = "", exit_code: int = 0) -> None:
        self.name, self.ok, self.detail, self.exit_code = name, ok, detail, exit_code


@pytest.fixture
def install_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("install.preinstall_assessment_tooling", lambda *a, **k: {"probe_exit": 0})
    monkeypatch.setattr(
        "install.probe_control_plane_during_install",
        lambda *a, **k: {"classification": "policy_denied"},
    )
    monkeypatch.setattr(
        "install.transition_to_verify_offline",
        lambda *a, **k: {"snapshot_group": "g", "phase": "verify"},
    )
    monkeypatch.setattr(
        "install.probe_offline_egress", lambda *a, **k: {"classification": "policy_denied"}
    )
    monkeypatch.setattr("selfheal.sandbox_alive", lambda *a, **k: True)


def _node_missing_run(seen: list[dict[str, Any]]) -> Any:
    """Fails until the plan installs nodejs/npm (a recoverable, evidence-driven failure)."""

    def _run(environment_id: str, profile: dict[str, Any], **_k: Any) -> list[Any]:
        seen.append(copy.deepcopy(profile))
        if {"nodejs", "npm"} <= set(profile.get("packages") or []):
            return [_Step("npm install", True)]
        return [_Step("npm install", False, "sh: 1: npm: not found", 127)]

    return _run


REVISED_NODE = {
    **NODE_PROFILE,
    "packages": ["nodejs", "npm"],
}


def test_install_failure_produces_a_justified_persisted_revision(
    llm: FakeLLM, install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _seed_install_job()
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr("install.run_install_commands", _node_missing_run(seen))
    llm.replies.append(
        {
            "profile": REVISED_NODE,
            "rationale": "npm exited 127 'not found': nodejs/npm missing from the debian image",
            "changes": ["packages: add nodejs, npm (evidence: npm: not found)"],
        }
    )

    result = provision_and_go_offline(job_id, settings=get_settings())

    # The failure text reached the planner; the revised plan is what ran next.
    assert len(llm.calls) == 1
    assert "npm: not found" in llm.calls[0][1]["content"]
    assert seen[0]["packages"] == []
    assert seen[1]["packages"] == ["nodejs", "npm"]
    assert result.install_failures == []
    assert result.repair_attempts == 2
    assert len(result.plan_revisions) == 1

    revs = get_ledger().list_profile_revisions(job_id)
    assert [r.phase for r in revs] == ["runtime", "runtime"]
    assert revs[-1].revision == result.plan_revisions[0]
    assert revs[-1].profile["packages"] == ["nodejs", "npm"]
    assert revs[-1].profile["source"]["commit"] == SHA
    repair_logs = [e for e in _events(job_id, "log") if e.payload.get("kind") == "repair"]
    assert any("nodejs/npm missing" in str(e.payload.get("rationale")) for e in repair_logs)
    job = get_ledger().get_job(job_id)
    assert job is not None and job.resolved_commit == SHA


def test_install_repair_without_inference_retries_same_plan(
    install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _seed_install_job()
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr("install.run_install_commands", _node_missing_run(seen))
    result = provision_and_go_offline(job_id, settings=get_settings())
    assert len(seen) == 3  # MAX_REPAIR_ATTEMPTS, unchanged plan each time
    assert all(p["packages"] == [] for p in seen)
    assert result.plan_revisions == []
    assert result.install_failures == ["npm install"]
    assert len(get_ledger().list_profile_revisions(job_id)) == 1


def test_install_unchanged_reply_is_a_plain_retry(
    llm: FakeLLM, install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    get_settings.cache_clear()
    job_id = _seed_install_job()
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr("install.run_install_commands", _node_missing_run(seen))
    llm.replies.append({"profile": NODE_PROFILE, "rationale": "looks transient, retry"})
    result = provision_and_go_offline(job_id, settings=get_settings())
    assert result.plan_revisions == []
    assert len(get_ledger().list_profile_revisions(job_id)) == 1
    assert len(seen) == 2


def test_install_repair_is_capped_by_max_repair_attempts(
    llm: FakeLLM, install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _seed_install_job()
    seen: list[dict[str, Any]] = []

    def _never_ok(environment_id: str, profile: dict[str, Any], **_k: Any) -> list[Any]:
        seen.append(profile)
        return [_Step("npm install", False, "still broken", 1)]

    monkeypatch.setattr("install.run_install_commands", _never_ok)
    for i in range(5):
        revised = copy.deepcopy(NODE_PROFILE)
        revised["packages"] = [f"pkg{i}"]
        llm.replies.append({"profile": revised, "rationale": f"try pkg{i}"})
    result = provision_and_go_offline(job_id, settings=get_settings())
    # 3 attempts => 2 repair iterations => at most 2 inference calls.
    assert len(seen) == 3
    assert len(llm.calls) == 2
    assert result.install_failures == ["npm install"]


def test_install_repair_respects_inference_budget(
    llm: FakeLLM, install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INFERENCE_BUDGET_TOKENS_PER_JOB", "100")
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    get_settings.cache_clear()
    job_id = _seed_install_job()
    get_ledger().update_job_fields(job_id, inference_usage={"total_tokens": 100})
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr("install.run_install_commands", _node_missing_run(seen))
    llm.replies.append({"profile": REVISED_NODE, "rationale": "x"})
    result = provision_and_go_offline(job_id, settings=get_settings())
    assert llm.calls == []
    assert result.plan_revisions == []
    assert len(seen) == 2


def test_install_repair_stops_at_job_deadline(
    llm: FakeLLM, install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _seed_install_job()
    seen: list[dict[str, Any]] = []
    expiring = _node_missing_run(seen)

    def _run(*a: Any, **k: Any) -> list[Any]:
        out = expiring(*a, **k)
        # Job deadline passes while attempt 1 is running.
        get_ledger().update_job_fields(job_id, expires_at="2000-01-01T00:00:00Z")
        return out

    monkeypatch.setattr("install.run_install_commands", _run)
    llm.replies.append({"profile": REVISED_NODE, "rationale": "x"})
    with pytest.raises(InstallError) as err:
        provision_and_go_offline(job_id, settings=get_settings())
    assert err.value.code == "deadline_exceeded"
    assert len(seen) == 1
    assert llm.calls == []


def test_install_demo_fallback_is_generated_and_keeps_original_failure(
    llm: FakeLLM, install_stubs: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    get_settings.cache_clear()
    job_id = _seed_install_job()

    def _run(environment_id: str, profile: dict[str, Any], **_k: Any) -> list[Any]:
        if profile["intent"] == "demo":
            return [_Step("true", True)]
        return [_Step("npm install", False, "ERESOLVE unable to resolve dependency tree", 1)]

    monkeypatch.setattr("install.run_install_commands", _run)
    demo = {
        **NODE_PROFILE,
        "intent": "demo",
        "runtime": "python",
        "packages": ["python3"],
        "install_commands": [],
        "run_commands": [
            {
                "argv": ["python3", "-m", "http.server", "8000", "--bind", "127.0.0.1"],
                "timeout_seconds": 60,
            }
        ],
        "processes": [],
        "ports": [8000],
        "probes": [
            {"name": "root", "type": "http", "url": "http://127.0.0.1:8000/", "accept": [200]}
        ],
        "summary": "static demo",
    }
    llm.replies.append({"profile": demo, "rationale": "dependency tree cannot be resolved"})
    result = provision_and_go_offline(job_id, settings=get_settings())
    assert result.install_failures == []
    final = get_ledger().list_profile_revisions(job_id)[-1].profile
    assert final["intent"] == "demo"
    assert final["verification_target"] == "generated_demo"
    assert final["original_failure"]["step"] == "install"
    assert "npm install" in final["original_failure"]["summary"]


# ---------------------------------------------------------------------------
# Verify repair
# ---------------------------------------------------------------------------


def _seed_verify_job() -> str:
    job_id = _seed_install_job()
    return job_id


def _verify_exec(port_ok: str, launched: list[str]) -> Any:
    def _exec(environment_id: str, cmd: Any, **_k: Any) -> ExecResult:
        joined = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if "nohup" in joined:
            launched.append(joined)
            return ExecResult("4242\n", "", 0)
        if "http_code" in joined:
            ok = f"127.0.0.1:{port_ok}" in joined
            return ExecResult(f"http_code:{200 if ok else 0}\n", "", 0)
        if "tail -c" in joined:
            return ExecResult("Error: listen EADDRINUSE: bind to 0.0.0.0:3000\n", "", 0)
        return ExecResult("", "", 0)

    return _exec


def test_verify_failure_revises_launch_plan_and_passes_honestly(
    llm: FakeLLM, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = _seed_verify_job()
    launched: list[str] = []
    monkeypatch.setattr("verify.exec_command", _verify_exec("3000", launched))
    revised = copy.deepcopy(NODE_PROFILE)
    revised["ports"] = [3000]
    revised["probes"][0]["url"] = "http://127.0.0.1:3000/"
    revised["processes"][0]["command"]["env"] = {"PORT": "3000"}
    # Locked in verify: these must not take effect.
    revised["intent"] = "demo"
    revised["packages"] = ["evil"]
    revised["install_commands"] = [{"shell": "true", "timeout_seconds": 5}]
    llm.replies.append(
        {
            "profile": revised,
            "rationale": "log shows the app listens on 3000, not 5000; probe and PORT follow",
            "changes": ["ports/probes: 5000 -> 3000 (evidence: listening on 3000)"],
        }
    )
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    get_settings.cache_clear()

    result = verify_readiness(job_id, settings=get_settings())

    assert result.passed is True
    assert result.verification_kind == "original_application"
    assert len(llm.calls) == 1
    assert "EADDRINUSE" in llm.calls[0][1]["content"]
    revs = get_ledger().list_profile_revisions(job_id)
    assert len(revs) == 2
    persisted = revs[-1].profile
    assert persisted["ports"] == [3000]
    assert persisted["intent"] == "webapp"
    assert persisted["packages"] == []
    assert persisted["install_commands"] == NODE_PROFILE["install_commands"]
    assert persisted["source"]["commit"] == SHA
    assert result.verify_result["plan_revisions"] == [revs[-1].revision]
    # Relaunched under the revised plan (exact launcher mechanics belong to verify.py).
    assert len(launched) >= 2
    assert not any("3000" in cmd for cmd in launched[:1])
    assert any("3000" in cmd for cmd in launched[1:])


def test_verify_repair_cannot_force_success(llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_verify_job()
    monkeypatch.setattr("verify.exec_command", _verify_exec("9999", []))
    revised = copy.deepcopy(NODE_PROFILE)
    revised["probes"][0]["url"] = "http://127.0.0.1:3000/"
    llm.replies.append({"profile": revised, "rationale": "guess port 3000"})
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    get_settings.cache_clear()
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is False
    assert result.verification_kind == "setup_failed"
    job = get_ledger().get_job(job_id)
    assert job is not None and job.readiness and job.readiness["passed"] is False


def test_verify_repair_stops_at_job_deadline(llm: FakeLLM, monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_verify_job()
    base = _verify_exec("9999", [])

    def _exec(environment_id: str, cmd: Any, **k: Any) -> ExecResult:
        get_ledger().update_job_fields(job_id, expires_at="2000-01-01T00:00:00Z")
        return base(environment_id, cmd, **k)

    monkeypatch.setattr("verify.exec_command", _exec)
    llm.replies.append({"profile": NODE_PROFILE, "rationale": "x"})
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "3")
    get_settings.cache_clear()
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is False
    assert llm.calls == []
    assert result.verify_result["code"] == "deadline_exceeded"


def test_verify_without_inference_keeps_plain_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = _seed_verify_job()
    launched: list[str] = []
    monkeypatch.setattr("verify.exec_command", _verify_exec("9999", launched))
    monkeypatch.setenv("MAX_REPAIR_ATTEMPTS", "2")
    get_settings.cache_clear()
    result = verify_readiness(job_id, settings=get_settings())
    assert result.passed is False
    assert len(launched) >= 2  # plain retry of the same plan
    assert not any("3000" in cmd for cmd in launched)
    assert len(get_ledger().list_profile_revisions(job_id)) == 1
