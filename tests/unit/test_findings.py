import json

import pytest
from pydantic import ValidationError

from aftwin.policy.findings import Finding, Severity, ValidationReport


def finding(
    rule_id: str,
    severity: Severity,
    *,
    target: str = "leaf-a1",
) -> Finding:
    return Finding(
        rule_id=rule_id,
        target=target,
        message=f"{rule_id} failed",
        hint=f"Fix {target}",
        severity=severity,
    )


def test_finding_is_strict_and_immutable() -> None:
    result = finding("GENERAL-001", Severity.ERROR)

    assert result.as_dict() == {
        "rule_id": "GENERAL-001",
        "target": "leaf-a1",
        "message": "GENERAL-001 failed",
        "hint": "Fix leaf-a1",
        "severity": "error",
    }
    with pytest.raises(ValidationError):
        result.message = "changed"
    with pytest.raises(ValidationError):
        Finding(
            rule_id="GENERAL-001",
            target="leaf-a1",
            message="Invalid severity",
            hint="Use a supported severity",
            severity="fatal",  # type: ignore[arg-type]
        )


def test_report_sorts_findings_and_computes_status() -> None:
    report = ValidationReport(
        findings=(
            finding("PLANE-002", Severity.INFO),
            finding("GENERAL-002", Severity.ERROR, target="spine-a1"),
            finding("GENERAL-001", Severity.ERROR),
            finding("CLOS-001", Severity.WARNING),
        )
    )

    assert [item.rule_id for item in report.findings] == [
        "GENERAL-001",
        "GENERAL-002",
        "CLOS-001",
        "PLANE-002",
    ]
    assert report.error_count == 2
    assert report.warning_count == 1
    assert report.info_count == 1
    assert report.failed
    assert not report.passed


def test_report_without_errors_passes() -> None:
    report = ValidationReport(findings=(finding("CLOS-001", Severity.WARNING),))

    assert report.passed
    assert not report.failed
    assert report.error_count == 0


def test_json_is_deterministic_and_machine_readable() -> None:
    first = finding("GENERAL-001", Severity.ERROR)
    second = finding("CLOS-001", Severity.WARNING)
    report = ValidationReport(findings=(second, first))

    assert report.to_json() == ValidationReport(findings=(first, second)).to_json()
    assert json.loads(report.to_json()) == report.as_dict()
    assert report.as_dict()["findings"] == [first.as_dict(), second.as_dict()]


def test_human_rendering_is_deterministic() -> None:
    report = ValidationReport(
        findings=(
            finding("CLOS-001", Severity.WARNING),
            finding("GENERAL-001", Severity.ERROR),
        )
    )

    assert report.render_human() == (
        "Static validation: FAIL\n"
        "Findings: 1 error(s), 1 warning(s), 0 info\n"
        "[ERROR] GENERAL-001 leaf-a1: GENERAL-001 failed\n"
        "  Hint: Fix leaf-a1\n"
        "[WARNING] CLOS-001 leaf-a1: CLOS-001 failed\n"
        "  Hint: Fix leaf-a1\n"
    )
