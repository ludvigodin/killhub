"""Plane-1 SCA + cite-checked review (D33, D43, D48)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import get_settings
from jobs import create_job, get_ledger, reset_ledger_for_tests
from vulnscan import (
    cite_checked_review,
    extract_packages,
    run_vuln_scan,
    sca_findings_from_lockfiles,
)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LEDGER_URL", f"sqlite:///{(tmp_path / 'l.db').as_posix()}")
    monkeypatch.setenv("REAPER_ENABLED", "false")
    monkeypatch.setenv("PREFLIGHT_ENABLED", "false")
    monkeypatch.setenv("ARTIFACT_STORAGE", str(tmp_path / "artifacts"))
    get_settings.cache_clear()
    reset_ledger_for_tests()
    yield
    reset_ledger_for_tests()
    get_settings.cache_clear()


def test_extract_npm_lock_packages(tmp_path: Path) -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "app", "version": "1.0.0"},
            "node_modules/lodash": {"version": "4.17.20"},
        },
    }
    path = tmp_path / "00-package-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")
    eco, pkgs = extract_packages(path)
    assert eco == "npm"
    assert ("lodash", "4.17.20") in pkgs


def test_cite_checked_review_drops_uncited() -> None:
    findings = [
        {
            "id": "sca-1",
            "severity": "high",
            "title": "Prototype pollution",
            "source": "sca",
        }
    ]
    draft = "Prototype pollution in lodash [sca-1]. Also remote code execution in imaginary-pkg."
    out = cite_checked_review(findings, draft=draft)
    assert "[sca-1]" in out
    assert "imaginary-pkg" not in out


@pytest.mark.parametrize(
    "draft",
    [
        "Minor issue [low-1].",
        "Unsupported claim [high-1][unknown].",
        "Too wordy " * 35 + "[high-1].",
    ],
)
def test_review_falls_back_to_highest_recorded_issue(draft: str) -> None:
    findings = [
        {"id": "low-1", "severity": "low", "title": "Minor issue"},
        {"id": "high-1", "severity": "high", "title": "Important warning"},
    ]
    assert cite_checked_review(findings, draft) == (
        "The scan flagged the following issue: Important warning [high-1]."
    )


def test_id_only_and_successful_protection_use_recorded_evidence():
    advisory = {
        "id": "sca-1",
        "source": "sca",
        "severity": "medium",
        "package": "example@1",
        "title": "GHSA-test",
        "detail": {"osv_id": "GHSA-test"},
    }
    denied = {
        "id": "offline",
        "source": "network",
        "severity": "info",
        "detail": {"classification": "policy_denied"},
    }
    text = cite_checked_review([denied, advisory], "This stole a password [sca-1].")
    assert "example@1" in text and "fixed version" in text and "stole" not in text
    assert "blocked a network connection as expected" in cite_checked_review([denied])


@pytest.mark.parametrize("response_id", ["GHSA-test", "GHSA-other"])
def test_advisory_enrichment_requires_matching_id(monkeypatch, response_id):
    from io import BytesIO

    from vulnscan import _enrich_sca_findings

    finding = {
        "detail": {"osv_id": "GHSA-test"},
        "title": "GHSA-test",
        "severity": "unknown",
        "source": "sca",
    }

    def lookup(req, timeout=None):  # noqa: ANN001
        url = req if isinstance(req, str) else getattr(req, "full_url", req)
        assert "GHSA-test" in str(url) and (timeout is None or timeout <= 3)
        return BytesIO(json.dumps({"id": response_id, "summary": "Published description"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", lookup)
    incomplete = _enrich_sca_findings([finding], deadline=__import__("time").monotonic() + 10)
    if response_id == "GHSA-test":
        assert finding["title"] == "Published description"
        assert incomplete is False
    else:
        assert finding["title"] == "GHSA-test"
        assert finding["severity"] == "unknown"
        assert incomplete is True


def test_sca_from_lockfile_with_mock_osv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "node_modules/left-pad": {"version": "1.3.0"},
        },
    }
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")

    def fake_osv(ecosystem, packages, **kwargs):
        assert ecosystem == "npm"
        return [
            {
                "package": "left-pad",
                "version": "1.3.0",
                "ecosystem": "npm",
                "osv_id": "GHSA-test",
                "summary": "test advisory",
                "aliases": [],
                "severity": "low",
                "advisory_url": "https://osv.dev/vulnerability/GHSA-test",
            }
        ]

    monkeypatch.setattr("vulnscan.query_osv_batch", fake_osv)
    findings, status, checked, discovered = sca_findings_from_lockfiles([path])
    assert checked == discovered == 1
    assert status == "ok"
    assert len(findings) == 1
    assert findings[0]["source"] == "sca"
    assert findings[0]["id"].startswith("sca-")


@pytest.mark.parametrize("sandbox_id", [None, "fixture-sandbox"])
def test_no_scan_inputs_persist_partial_report(monkeypatch, sandbox_id):
    job = create_job("https://github.com/example/fixture")
    ledger = get_ledger()
    ledger.update_job_fields(job.job_id, sandbox_id=sandbox_id)
    monkeypatch.setattr("vulnscan.copy_lockfiles_to_artifacts", lambda *args, **kwargs: ([], False))
    result = run_vuln_scan(job.job_id)
    report = ledger.get_vuln_report(job.job_id)
    assert result.status == report["status"] == "partial"
    assert "No dependency files" in report["summary"]
    assert report["findings"] == []


def test_unsupported_file_is_partial(tmp_path):
    path = tmp_path / "Cargo.lock"
    path.write_text("")
    assert sca_findings_from_lockfiles([path]) == ([], "partial", 0, 0)


@pytest.mark.parametrize(
    "case", ["matched", "mismatch", "changed_file", "late", "missing", "unbound_commit", "online"]
)
def test_pinned_read_assessment_receipt(case, monkeypatch):
    from discover import infer_runtime_profile
    from fixtures import require_fixture
    from harness import ExecResult
    from operator_mcp_tools import summarize_receipt

    fixture = require_fixture("git_mcp_filesystem")
    job = create_job(fixture["github_url"])
    ledger = get_ledger()
    profile = infer_runtime_profile(
        github_url=job.github_url,
        commit=fixture["commit"],
        inspect={},
        fixture=fixture,
        oci_image="debian",
    )
    ledger.append_profile_revision(job.job_id, phase="runtime", schema_version="1", profile=profile)
    ledger.update_job_fields(
        job.job_id,
        sandbox_id="env-fixture",
        resolved_commit=("0" * 40 if case == "unbound_commit" else fixture["commit"]),
        readiness={"passed": True},
        verification={"kind": "original_application"},
    )
    ledger.append_event(
        job.job_id,
        typ="lifecycle",
        message="restore",
        payload={
            "phase": "network_verify",
            "environment_id": "env-fixture",
            "net": {"no_net": True},
        },
    )
    ledger.append_event(
        job.job_id,
        typ="log",
        message="install",
        payload={
            "kind": "install",
            "offline_probe": {
                "classification": "policy_bypass" if case == "online" else "policy_denied"
            },
        },
    )

    def measure(env, cmd, **kwargs):
        assert case not in ("unbound_commit", "online")
        assert cmd[-1] == "/opt/killhub/helpers/mcp_fixture_read.py"
        data = {
            "tool": "read_text_file",
            "status": "passed",
            "expected_sha256": "1" * 64,
            "schema_sha256": "3" * 64,
            "response_sha256": ("2" if case == "mismatch" else "1") * 64,
            "elapsed_ms": 15001 if case == "late" else 51,
            "fixture_unchanged": case != "changed_file",
        }
        return ExecResult(
            stdout="{}" if case == "missing" else json.dumps(data), stderr="", exit_code=0
        )

    monkeypatch.setattr("vulnscan.exec_command", measure)
    monkeypatch.setattr("vulnscan.copy_lockfiles_to_artifacts", lambda *a, **kw: ([], False))
    result = run_vuln_scan(job.job_id)
    expected = {
        "matched": "passed",
        "mismatch": "failed",
        "changed_file": "failed",
        "late": "failed",
        "missing": "partial",
        "unbound_commit": "skipped",
        "online": "skipped",
    }[case]
    assert result.mcp_assessment["status"] == expected
    snap = ledger.get_snapshot(job.job_id)
    assert (
        summarize_receipt(snap, base_url="https://example.test")["mcp_assessment"]
        == result.mcp_assessment
    )
    assert snap["readiness"]["passed"]


@pytest.mark.parametrize("has_completed_lookup", [False, True])
def test_unavailable_advisory_lookup_preserves_coverage(
    tmp_path, monkeypatch, has_completed_lookup
):
    npm = tmp_path / "package-lock.json"
    npm.write_text(json.dumps({"packages": {"node_modules/pkg": {"version": "1.0.0"}}}))
    python = tmp_path / "requirements.txt"
    python.write_text("fixture==1.0.0\n")

    def lookup(ecosystem, packages, **kwargs):
        if ecosystem == "npm":
            raise TimeoutError("advisory lookup unavailable")
        return []

    monkeypatch.setattr("vulnscan.query_osv_batch", lookup)
    inputs = [npm, python] if has_completed_lookup else [npm]
    assert sca_findings_from_lockfiles(inputs) == (
        [],
        "partial" if has_completed_lookup else "failed",
        int(has_completed_lookup),
        len(inputs),
    )


@pytest.mark.parametrize(
    "limit,fail_second,expected",
    [(3, False, ("ok", 161)), (1, False, ("partial", 80)), (3, True, ("partial", 80))],
)
def test_large_lock_coverage(tmp_path, monkeypatch, limit, fail_second, expected):
    path = tmp_path / "requirements.txt"
    path.write_text("".join(f"pkg{i}==1\n" for i in range(161)))
    batches = []

    def lookup(ecosystem, packages, **kwargs):
        assert 0 < kwargs["timeout"] <= 30
        assert len(packages) <= 80
        if batches and fail_second:
            raise TimeoutError
        batches.extend(packages)
        return []

    monkeypatch.setattr("vulnscan.OSV_MAX_BATCHES", limit)
    monkeypatch.setattr("vulnscan.query_osv_batch", lookup)
    _, status, checked, discovered = sca_findings_from_lockfiles([path])
    assert (status, checked) == expected
    assert discovered == 161
    assert len(set(batches)) == checked


def test_osv_severity_from_cvss_vector() -> None:
    from vulnscan import _osv_severity

    # CVSS:3.1 critical (9.8) — previously misclassified as medium.
    critical = {
        "severity": [
            {
                "type": "CVSS_V3",
                "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            }
        ]
    }
    assert _osv_severity(critical) == "critical"

    high = {
        "severity": [
            {
                "type": "CVSS_V3",
                "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            }
        ]
    }
    assert _osv_severity(high) == "high"

    assert _osv_severity({"database_specific": {"severity": "HIGH"}}) == "high"
    assert _osv_severity({"affected": [{"ecosystem_specific": {"severity": "low"}}]}) == "low"
    assert _osv_severity({"id": "GHSA-empty"}) == "unknown"


def test_id_only_batch_enriches_severity_and_aliases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {
            "node_modules/left-pad": {"version": "1.3.0"},
            "node_modules/right-pad": {"version": "1.0.0"},
        },
    }
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")

    def fake_batch(ecosystem, packages, **kwargs):
        return [
            {
                "package": name,
                "version": version,
                "ecosystem": "npm",
                "osv_id": "GHSA-shared",
                "summary": "GHSA-shared",
                "aliases": [],
                "severity": "unknown",
                "advisory_url": "https://osv.dev/vulnerability/GHSA-shared",
            }
            for name, version in packages
        ]

    fetches: list[str] = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _n: int = -1):
            return json.dumps(
                {
                    "id": "GHSA-shared",
                    "summary": "Shared advisory title",
                    "aliases": ["CVE-2024-0001"],
                    "severity": [
                        {
                            "type": "CVSS_V3",
                            "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
                        }
                    ],
                }
            ).encode()

    def fake_urlopen(url, timeout=None):  # noqa: ANN001
        fetches.append(str(url))
        return _Resp()

    monkeypatch.setattr("vulnscan.query_osv_batch", fake_batch)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    findings, status, checked, discovered = sca_findings_from_lockfiles([path])
    assert status == "ok"
    assert checked == discovered == 2
    assert len(findings) == 2
    assert all(f["severity"] == "critical" for f in findings)
    assert all(f["title"] == "Shared advisory title" for f in findings)
    assert all(f["detail"]["aliases"] == ["CVE-2024-0001"] for f in findings)
    # One GET cached across two packages sharing the advisory id.
    assert len(fetches) == 1


def test_enrichment_timeout_keeps_unknown_and_marks_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = {
        "lockfileVersion": 3,
        "packages": {"node_modules/left-pad": {"version": "1.3.0"}},
    }
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(lock), encoding="utf-8")

    def fake_batch(ecosystem, packages, **kwargs):
        return [
            {
                "package": "left-pad",
                "version": "1.3.0",
                "ecosystem": "npm",
                "osv_id": "GHSA-timeout",
                "summary": "GHSA-timeout",
                "aliases": [],
                "severity": "unknown",
                "advisory_url": "https://osv.dev/vulnerability/GHSA-timeout",
            }
        ]

    monkeypatch.setattr("vulnscan.query_osv_batch", fake_batch)
    # Soft-fail path: fetch returns None rather than raising.
    monkeypatch.setattr("vulnscan._fetch_osv_vuln", lambda *_a, **_k: None)
    findings, status, checked, discovered = sca_findings_from_lockfiles([path])
    assert checked == discovered == 1
    assert len(findings) == 1
    assert findings[0]["severity"] == "unknown"
    assert findings[0]["detail"]["osv_id"] == "GHSA-timeout"
    assert status == "partial"


def test_control_fixture_review_prioritizes_scan_over_metadata_warning(monkeypatch, tmp_path):
    job = create_job("https://github.com/example/fixture")
    ledger = get_ledger()
    ledger.update_job_fields(job.job_id, sandbox_id="fixture")
    ledger.append_event(
        job.job_id,
        typ="finding",
        message="GitHub metadata unavailable",
        payload={"source": "preflight", "code": "github_api_limited", "severity": "low"},
    )
    lock = tmp_path / "requirements.txt"
    lock.write_text("pkg==1.0\n")
    monkeypatch.setattr("vulnscan.copy_lockfiles_to_artifacts", lambda *a, **kw: ([lock], False))
    monkeypatch.setattr("vulnscan.query_osv_batch", lambda *a, **kw: [])
    run_vuln_scan(job.job_id)
    report = ledger.get_vuln_report(job.job_id)
    assert report["summary"].startswith(
        "Checked 1 of 1 listed dependency versions. No known advisories"
    )
    assert "GitHub" not in report["summary"]
    assert any(f["id"] == "github_api_limited" for f in report["findings"])
