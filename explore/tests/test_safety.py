"""summary_safety enum for job feed stamps."""

from __future__ import annotations

from safety import summary_safety


def _receipt(
    *,
    claim: str = "proven",
    kind: str = "original_application",
    reasons: list[str] | None = None,
) -> dict:
    return {
        "verification": {"kind": kind},
        "containment": {"claim": claim},
        "dossier": {"gates": {"reasons": reasons or []}},
    }


def _ok_report(findings: list | None = None) -> dict:
    return {
        "status": "ok",
        "summary": "Scanned surfaces.",
        "findings": findings if findings is not None else [],
    }


def test_none_while_running() -> None:
    assert (
        summary_safety(
            status="analyzing",
            verification=None,
            vuln_report=_ok_report(),
            receipt=_receipt(),
        )
        is None
    )


def test_none_without_receipt() -> None:
    assert (
        summary_safety(
            status="completed",
            verification={"kind": "original_application"},
            vuln_report=_ok_report(),
            receipt=None,
        )
        is None
    )


def test_safe_when_gates_pass() -> None:
    assert (
        summary_safety(
            status="completed",
            verification={"kind": "original_application"},
            vuln_report=_ok_report(),
            receipt=_receipt(),
        )
        == "safe"
    )


def test_high_risk_from_critical_finding() -> None:
    assert (
        summary_safety(
            status="completed",
            verification=None,
            vuln_report=_ok_report([{"severity": "critical", "title": "x"}]),
            receipt=_receipt(),
        )
        == "high_risk"
    )


def test_high_risk_from_policy_bypass() -> None:
    assert (
        summary_safety(
            status="completed",
            verification=None,
            vuln_report=_ok_report(),
            receipt=_receipt(reasons=["containment_policy_bypass"]),
        )
        == "high_risk"
    )


def test_review_from_medium_finding() -> None:
    assert (
        summary_safety(
            status="completed",
            verification=None,
            vuln_report=_ok_report([{"severity": "medium", "title": "x"}]),
            receipt=_receipt(),
        )
        == "review"
    )


def test_review_from_unknown_finding_severity() -> None:
    assert (
        summary_safety(
            status="completed",
            verification={"kind": "original_application"},
            vuln_report=_ok_report([{"severity": "unknown", "title": "GHSA-x", "source": "sca"}]),
            receipt=_receipt(),
        )
        == "review"
    )


def test_unknown_when_containment_not_proven() -> None:
    assert (
        summary_safety(
            status="completed",
            verification={"kind": "original_application"},
            vuln_report=_ok_report(),
            receipt=_receipt(claim="incomplete"),
        )
        == "unknown"
    )


def test_unknown_for_failed_terminal() -> None:
    assert (
        summary_safety(
            status="failed",
            verification={"kind": "original_application"},
            vuln_report=_ok_report(),
            receipt=_receipt(),
        )
        == "unknown"
    )


def test_uses_receipt_verification_when_job_verification_missing() -> None:
    assert (
        summary_safety(
            status="completed",
            verification=None,
            vuln_report=_ok_report(),
            receipt=_receipt(kind="original_application"),
        )
        == "safe"
    )
