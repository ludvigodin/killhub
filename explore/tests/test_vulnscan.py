"""Plane-1 SCA + cite-checked review (D33, D43, D48)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import get_settings
from jobs import reset_ledger_for_tests
from vulnscan import cite_checked_review, extract_packages, sca_findings_from_lockfiles


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
    findings, status = sca_findings_from_lockfiles([path])
    assert status == "ok"
    assert len(findings) == 1
    assert findings[0]["source"] == "sca"
    assert findings[0]["id"].startswith("sca-")


def test_cite_checked_deterministic_clean_bill() -> None:
    assert "Clean bill" in cite_checked_review([])
