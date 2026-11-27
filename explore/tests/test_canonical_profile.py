"""Exercise the Plane 1 runtime-profile contract without launching guest commands.

New discovery profiles must validate before storage. Old ledger rows are
translated only when an existing job needs a validated execution profile.
"""

from __future__ import annotations

import json
from pathlib import Path
from profile import (
    ProfileError,
    assert_runtime_ready_for_provision,
    load_schema,
    persist_profile_revision,
    validate_profile,
)
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from config import Settings
from discover import DiscoverError, discover_runtime_profile, infer_runtime_profile
from fixtures import require_fixture
from jobs import get_ledger, reset_ledger_for_tests


def _fixture_profile(fixture_id: str) -> dict[str, Any]:
    fixture = require_fixture(fixture_id)
    return infer_runtime_profile(
        github_url=fixture["github_url"],
        commit=fixture["commit"],
        inspect={},
        fixture=fixture,
        oci_image="debian",
    )


@pytest.mark.parametrize("fixture_id", ["webapp_success", "git_mcp_filesystem"])
def test_discovered_profile_keeps_canonical_shape_in_storage(
    tmp_path: Path, fixture_id: str
) -> None:
    settings = Settings(
        _env_file=None,
        LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        PROFILE_STORAGE=str(tmp_path / "profiles"),
    )
    profile = _fixture_profile(fixture_id)
    validator = Draft202012Validator(load_schema())
    validator.validate(profile)
    assert profile["commands"]["install"]
    assert profile["commands"]["run"]
    assert profile["source"]["commit"] == require_fixture(fixture_id)["commit"]

    ledger = get_ledger(settings)
    try:
        job = ledger.create_job(profile["source"]["url"], env_ttl_seconds=60)
        revision = persist_profile_revision(job.job_id, profile, phase="runtime", settings=settings)
        saved = json.loads(Path(revision.storage_path).read_text(encoding="utf-8"))
        validator.validate(saved)
        assert saved == profile
        snapshot = ledger.get_snapshot(job.job_id)
        assert snapshot is not None
        assert snapshot["profile"] == profile
    finally:
        reset_ledger_for_tests()


def test_runtime_validation_rejects_mixed_command_shapes() -> None:
    profile = _fixture_profile("webapp_success")
    profile["commands"]["install"][0]["shell"] = "true"
    with pytest.raises(ProfileError, match="runtime profile failed"):
        validate_profile(profile, phase="runtime")


def test_legacy_runtime_requires_explicit_read_adapter() -> None:
    canonical = _fixture_profile("webapp_success")
    legacy = {
        key: value
        for key, value in canonical.items()
        if key not in {"commands", "network_mode", "cgroup_limits", "source", "probes"}
    }
    legacy["source"] = {**canonical["source"], "type": "git"}
    legacy["install_commands"] = canonical["commands"]["install"]
    legacy["run_commands"] = canonical["commands"]["run"]
    probe = dict(canonical["probes"][0])
    probe["accept"] = probe.pop("expected_statuses")
    legacy["probes"] = [probe]

    with pytest.raises(ProfileError, match="runtime profile failed"):
        validate_profile(legacy, phase="runtime")

    assert assert_runtime_ready_for_provision(legacy, stored=True) == canonical
    assert legacy["source"]["type"] == "git"
    assert "accept" in legacy["probes"][0]


def test_discovery_rejects_catalog_pin_change_before_bootstrap(tmp_path: Path) -> None:
    fixture = require_fixture("webapp_success")
    settings = Settings(
        _env_file=None,
        LEDGER_URL=f"sqlite:///{tmp_path / 'ledger.db'}",
        PROFILE_STORAGE=str(tmp_path / "profiles"),
    )
    ledger = get_ledger(settings)
    try:
        job = ledger.create_job(fixture["github_url"], env_ttl_seconds=60)
        # Simulate a queued job admitted against a prior catalog revision.
        previous = "b" * 40
        ledger.update_job_fields(job.job_id, resolved_commit=previous)
        with pytest.raises(DiscoverError) as error:
            discover_runtime_profile(job.job_id, settings=settings)
        assert error.value.code == "fixture_pin_changed"
        assert ledger.list_profile_revisions(job.job_id) == []
        saved = ledger.get_job(job.job_id)
        assert saved is not None and saved.resolved_commit == previous and saved.sandbox_id is None
    finally:
        reset_ledger_for_tests()
