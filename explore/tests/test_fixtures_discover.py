"""Pinned fixtures (D53) + bootstrap discover / profile validation (D36, D51, D62)."""

from __future__ import annotations

from pathlib import Path
from profile import (
    ProfileError,
    assert_runtime_ready_for_provision,
    bootstrap_profile,
    persist_profile_revision,
    validate_profile,
)
from typing import Sequence

import pytest

from config import get_settings
from discover import (
    DiscoverError,
    discover_runtime_profile,
    infer_runtime_profile,
)
from fixtures import list_fixtures, match_fixture, require_fixture
from harness import ExecResult
from jobs import get_ledger, reset_ledger_for_tests
from service import create_job


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'ledger.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("MSB_AUTO_CREATE", "false")
    monkeypatch.setenv("PROFILE_STORAGE", str(tmp_path / "profiles"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def test_m7_fixtures_have_full_shas() -> None:
    fixtures = list_fixtures()
    assert set(fixtures) >= {
        "webapp_success",
        "git_mcp_filesystem",
        "setup_failed",
    }
    for fixture in fixtures.values():
        commit = fixture["commit"]
        assert isinstance(commit, str) and len(commit) == 40
        assert all(c in "0123456789abcdef" for c in commit)
        assert fixture["github_url"].startswith("https://github.com/")
    mcp = require_fixture("git_mcp_filesystem")["mcp"]
    assert mcp["entrypoint"] == "src/filesystem"
    assert mcp["transport"] == "stdio"
    assert require_fixture("setup_failed")["forbid_demo_intent"] is True


def test_match_fixture_by_url() -> None:
    for url in (
        "https://github.com/heroku/node-js-getting-started/",
        "https://github.com/heroku/nodejs-getting-started",
    ):
        hit = match_fixture(url)
        assert hit is not None, url
        assert hit["id"] == "webapp_success"
    # Image-replace variant is require_fixture-only (same canonical URL).
    assert require_fixture("webapp_image_replace")["oci_image"] == "alpine"
    assert require_fixture("webapp_image_replace").get("match_by_url") is False


def test_bootstrap_and_runtime_validation() -> None:
    boot = bootstrap_profile(
        github_url="https://github.com/heroku/node-js-getting-started",
        oci_image="debian",
    )
    validate_profile(boot, phase="bootstrap")

    web = require_fixture("webapp_success")
    profile = infer_runtime_profile(
        github_url=web["github_url"],
        commit=web["commit"],
        inspect={"has_package_json": True, "mentions_express": True},
        fixture=web,
        oci_image="debian",
    )
    validate_profile(profile, phase="runtime")
    assert profile["source"]["commit"] == web["commit"]
    assert profile["intent"] == "webapp"

    mcp_fix = require_fixture("git_mcp_filesystem")
    mcp_profile = infer_runtime_profile(
        github_url=mcp_fix["github_url"],
        commit=mcp_fix["commit"],
        inspect={"has_filesystem_mcp": True, "mentions_mcp": True},
        fixture=mcp_fix,
        oci_image="debian",
    )
    validate_profile(mcp_profile, phase="runtime")
    assert mcp_profile["mcp"]["transport"] == "stdio"
    assert mcp_profile["source"]["commit"] == mcp_fix["commit"]


def test_runtime_missing_commit_rejected() -> None:
    web = require_fixture("webapp_success")
    profile = infer_runtime_profile(
        github_url=web["github_url"],
        commit=web["commit"],
        inspect={"has_package_json": True, "mentions_express": True},
        fixture=web,
        oci_image="debian",
    )
    profile["source"].pop("commit")
    with pytest.raises(ProfileError) as err:
        validate_profile(profile, phase="runtime")
    assert err.value.code == "missing_commit"
    with pytest.raises(Exception) as blocked:
        assert_runtime_ready_for_provision(profile)
    assert getattr(blocked.value, "code", "") == "profile_blocks_provision"


def test_setup_failed_fixture_forbids_demo() -> None:
    fail = require_fixture("setup_failed")
    with pytest.raises(DiscoverError) as err:
        infer_runtime_profile(
            github_url=fail["github_url"],
            commit=fail["commit"],
            inspect={},
            fixture=fail,
            oci_image="debian",
        )
    assert err.value.code == "setup_failed_fixture"


class _FakeExec:
    """Simulates in-guest clone/inspect without msb."""

    def __init__(self, *, commit: str, inspect_stdout: str) -> None:
        self.commit = commit
        self.inspect_stdout = inspect_stdout
        self.calls: list[str] = []

    def __call__(
        self,
        environment_id: str,
        cmd: Sequence[str] | str,
        *,
        job_id: str | None = None,
        timeout: float | None = None,
        settings=None,
        cli=None,
    ) -> ExecResult:
        if isinstance(cmd, (list, tuple)):
            joined = " ".join(str(c) for c in cmd)
        else:
            joined = str(cmd)
        self.calls.append(joined)
        if "command -v git" in joined:
            return ExecResult(stdout="/usr/bin/git\n", stderr="", exit_code=0)
        if "git rev-parse HEAD" in joined:
            return ExecResult(stdout=f"{self.commit}\n", stderr="", exit_code=0)
        if "git clone" in joined or "git fetch" in joined or "git checkout" in joined:
            return ExecResult(stdout="", stderr="", exit_code=0)
        if "rm -rf" in joined or "mkdir" in joined:
            return ExecResult(stdout="", stderr="", exit_code=0)
        if "---TREE---" in joined or "find ." in joined:
            return ExecResult(stdout=self.inspect_stdout, stderr="", exit_code=0)
        return ExecResult(stdout="", stderr="", exit_code=0)


def test_discover_webapp_fixture_emits_runtime_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    web = require_fixture("webapp_success")
    fake = _FakeExec(
        commit=web["commit"],
        inspect_stdout=(
            "---TREE---\n./package.json\n./index.js\n"
            '---PACKAGE_JSON---\n{"name":"node-js-getting-started","dependencies":{"express":"4.18.2"}}\n'
            "---README---\nGetting Started\n"
        ),
    )

    # Skip real msb create; attach a fake sandbox id.
    monkeypatch.setattr(
        "discover.create_environment",
        lambda *a, **k: type(
            "G",
            (),
            {
                "environment_id": "env-fake",
                "generation": 1,
                "state": "running",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )(),
    )
    monkeypatch.setattr("discover.wait_until_ready", lambda *a, **k: None)
    monkeypatch.setattr("discover.destroy_job_environment", lambda *a, **k: None)

    job = create_job(web["github_url"])
    result = discover_runtime_profile(
        job.job_id,
        exec_fn=fake,
        create=True,
        destroy_on_failure=False,
    )
    assert result.resolved_commit == web["commit"]
    assert result.profile["intent"] == "webapp"
    assert result.profile["source"]["commit"] == web["commit"]
    validate_profile(result.profile, phase="runtime")

    refreshed = get_ledger().get_job(job.job_id)
    assert refreshed is not None
    assert refreshed.resolved_commit == web["commit"]
    assert refreshed.current_profile_revision == 2  # bootstrap + runtime
    revs = get_ledger().list_profile_revisions(job.job_id)
    assert revs[0].phase == "bootstrap"
    assert revs[1].phase == "runtime"
    assert Path(revs[1].storage_path).is_file()


def test_discover_mcp_fixture_emits_git_mcp_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mcp = require_fixture("git_mcp_filesystem")
    fake = _FakeExec(
        commit=mcp["commit"],
        inspect_stdout=(
            "---TREE---\n./src/filesystem/package.json\n"
            "---MCP_FS---\nindex.ts\npackage.json\n"
            '---PACKAGE_JSON---\n{"name":"@modelcontextprotocol/server-filesystem"}\n'
        ),
    )
    monkeypatch.setattr(
        "discover.create_environment",
        lambda *a, **k: type(
            "G",
            (),
            {
                "environment_id": "env-mcp",
                "generation": 1,
                "state": "running",
                "expires_at": "2099-01-01T00:00:00Z",
            },
        )(),
    )
    monkeypatch.setattr("discover.wait_until_ready", lambda *a, **k: None)

    job = create_job(mcp["github_url"])
    result = discover_runtime_profile(
        job.job_id, exec_fn=fake, create=True, destroy_on_failure=False
    )
    assert result.profile["intent"] == "git_mcp"
    assert result.profile["mcp"]["entrypoint"] == "src/filesystem"
    assert result.fixture_id == "git_mcp_filesystem"


def test_persist_profile_revision_writes_storage(tmp_path: Path) -> None:
    job = create_job("https://github.com/heroku/node-js-getting-started")
    boot = bootstrap_profile(
        github_url=job.github_url,
        oci_image="debian",
    )
    rev = persist_profile_revision(job.job_id, boot, phase="bootstrap")
    assert Path(rev.storage_path).is_file()
    assert "bootstrap" in Path(rev.storage_path).read_text(encoding="utf-8")
