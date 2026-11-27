"""Golden demo scenarios: each repo must end with the outcome the product promises."""

from __future__ import annotations

import re

import pytest
from conftest import SCENARIOS, Scenario, finding_code, finding_codes, findings

pytestmark = pytest.mark.slow

_IDS = [s.name for s in SCENARIOS]


@pytest.mark.parametrize("sc", SCENARIOS, ids=_IDS)
def test_terminal_status_and_honest_label(scenario_run, sc: Scenario) -> None:
    snap = scenario_run.results[sc.name]
    assert snap["status"] == sc.status, (sc.name, snap["status"], snap.get("error"))
    if sc.kind:
        assert (snap.get("verification") or {}).get("kind") == sc.kind, snap.get("verification")


@pytest.mark.parametrize(
    "sc", [s for s in SCENARIOS if s.readiness is not None], ids=lambda s: s.name
)
def test_readiness_evidence(scenario_run, sc: Scenario) -> None:
    ready = scenario_run.results[sc.name].get("readiness") or {}
    assert ready.get("passed") is sc.readiness, ready
    if sc.readiness_probe:
        assert str(ready.get("probe", "")).startswith(sc.readiness_probe), ready.get("probe")


@pytest.mark.parametrize(
    "sc", [s for s in SCENARIOS if s.readiness_probe == "mcp_handshake"], ids=lambda s: s.name
)
def test_mcp_servers_complete_a_real_handshake(scenario_run, sc: Scenario) -> None:
    detail = (scenario_run.results[sc.name].get("readiness") or {}).get("detail") or {}
    evidence = detail.get("evidence") or {}
    assert evidence.get("ok") is True, detail
    assert evidence.get("tool_count", 0) >= sc.extra.get("min_tools", 1), evidence.get("tool_count")


@pytest.mark.parametrize("sc", [s for s in SCENARIOS if s.sca_packages], ids=lambda s: s.name)
def test_known_vulnerable_dependencies_are_reported(scenario_run, sc: Scenario) -> None:
    pkgs = [
        str(f.get("package") or "")
        for f in findings(scenario_run.results[sc.name])
        if f.get("source") == "sca"
    ]
    for want in sc.sca_packages:
        assert any(p.lower().startswith(want.lower()) for p in pkgs), (want, pkgs)


@pytest.mark.parametrize("sc", [s for s in SCENARIOS if s.no_sca], ids=lambda s: s.name)
def test_control_repo_has_no_advisories(scenario_run, sc: Scenario) -> None:
    snap = scenario_run.results[sc.name]
    assert [f for f in findings(snap) if f.get("source") == "sca"] == []
    assert (snap.get("vuln_report") or {}).get("status") in {"ok", "partial"}


def test_python_mcp_lockfile_is_scanned(scenario_run) -> None:
    report = scenario_run.results["python_mcp_vultr"].get("vuln_report") or {}
    assert "No dependency files" not in (report.get("summary") or ""), report.get("summary")
    assert any(f.get("source") == "sca" for f in report.get("findings") or []), (
        "uv.lock not scanned"
    )


@pytest.mark.parametrize("sc", [s for s in SCENARIOS if s.finding_codes], ids=lambda s: s.name)
def test_required_security_findings(scenario_run, sc: Scenario) -> None:
    codes = finding_codes(scenario_run.results[sc.name])
    assert set(sc.finding_codes) <= codes, (sc.finding_codes, codes)


@pytest.mark.parametrize("sc", [s for s in SCENARIOS if s.forbidden_codes], ids=lambda s: s.name)
def test_no_false_positive_security_findings(scenario_run, sc: Scenario) -> None:
    codes = finding_codes(scenario_run.results[sc.name])
    assert not (set(sc.forbidden_codes) & codes), codes


def test_canary_exfiltration_hard_fails_the_job(scenario_run) -> None:
    snap = scenario_run.results["leaky_install"]
    assert snap["status"] == "failed"
    assert "policy_bypass" in str(snap.get("error") or ""), snap.get("error")
    exfil = [f for f in findings(snap) if finding_code(f) == "canary_exfiltration"]
    assert exfil, findings(snap)
    assert (exfil[0].get("severity") or "").lower() == "critical"
    # Destination recorded but the canary itself redacted.
    hits = exfil[0].get("hits") or (exfil[0].get("detail") or {}).get("hits") or []
    for hit in hits:
        dest = str(hit.get("destination", ""))
        if hit.get("channel") == "dns":
            assert dest.startswith("<canary>"), dest


def test_setup_failed_is_not_labelled_as_working(scenario_run) -> None:
    snap = scenario_run.results["setup_failed"]
    verification = snap.get("verification") or {}
    assert verification.get("kind") == "setup_failed"
    assert verification.get("kind") != "original_application"


def test_vuln_summaries_only_cite_real_findings(scenario_run) -> None:
    for name, snap in scenario_run.results.items():
        report = snap.get("vuln_report") or {}
        ids = {str(f.get("id")) for f in report.get("findings") or [] if f.get("id")}
        cited = set(re.findall(r"\[([A-Za-z0-9_.:-]+)\]", report.get("summary") or ""))
        assert cited <= ids, (name, sorted(cited - ids))
