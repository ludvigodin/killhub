"""Plane 1 review tests. Model suggestions prioritize recorded evidence only."""

from __future__ import annotations

import json

from inference_extras import _findings_user_payload
from vulnscan import _render_review, cite_checked_review


def test_known_finding_cannot_authorize_unsupported_draft_text() -> None:
    findings = [{"id": "sca-1", "severity": "high", "title": "Recorded dependency advisory"}]
    draft = "The host leaked a credential [sca-1]. [invented-2]"

    summary, used_draft = _render_review(findings, draft)

    assert not used_draft
    assert "Recorded dependency advisory [sca-1]" in summary
    assert "leaked" not in summary
    assert "invented-2" not in summary


def test_review_priorities_cannot_hide_omitted_severity_or_inject_citations() -> None:
    findings = [
        {"id": "sca-1", "severity": "medium", "title": "First advisory [sca-2]"},
        {"id": "sca-2", "severity": "medium", "title": "Second advisory"},
        {"id": "sca-3", "severity": "critical", "title": "Critical advisory"},
    ]
    draft = "[unknown]\n[sca-2]\n[sca-2]"

    summary, used_draft = _render_review(findings, draft)

    assert used_draft
    assert summary.index("[sca-3]") < summary.index("[sca-2]") < summary.index("[sca-1]")
    assert summary.count("[sca-2]") == 1
    assert "First advisory (sca-2) [sca-1]" in summary
    assert "[unknown]" not in summary


def test_review_payload_serializes_bounded_redacted_evidence() -> None:
    title = "Authorization: Bearer fixture-credential\ntoken=fixture-secret\n" + "x" * 400
    findings = [{"id": "sca-1", "title": title, "advisory_url": "https://example.com"}]

    payload = json.loads(_findings_user_payload(findings))
    row = payload["findings"][0]
    assert row["id"] == "sca-1"
    assert "fixture-secret" not in row["title"]
    assert "fixture-credential" not in row["title"]
    assert len(row["title"]) == 300
    assert "advisory_url" not in row
    assert "fixture-secret" not in cite_checked_review(findings)
    assert "fixture-credential" not in cite_checked_review(findings)
