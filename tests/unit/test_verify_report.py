"""Tests for stable human and JSON runtime reports."""

from aftwin.verify.report import (
    VerificationCategory,
    VerificationFinding,
    VerificationReport,
    VerificationSection,
)


def finding(rule_id: str, target: str) -> VerificationFinding:
    return VerificationFinding(
        rule_id=rule_id,
        category=VerificationCategory.BGP,
        target=target,
        message="session is not established",
        hint="Inspect the fabric link.",
    )


def test_report_is_stable_independent_of_input_order() -> None:
    first = VerificationSection(name="routes", expected=2, passed=2, findings=())
    second = VerificationSection(
        name="bgp-sessions",
        expected=2,
        passed=0,
        findings=(finding("BGP005", "z"), finding("BGP001", "a")),
    )

    report = VerificationReport(sections=(first, second))
    reordered = VerificationReport(
        sections=(
            VerificationSection(
                name="bgp-sessions",
                expected=2,
                passed=0,
                findings=tuple(reversed(second.findings)),
            ),
            first,
        )
    )

    assert report.to_json() == reordered.to_json()
    assert report.to_json().endswith("\n")
    assert not report.passed


def test_human_report_is_actionable_and_newline_terminated() -> None:
    report = VerificationReport(
        sections=(
            VerificationSection(
                name="bgp-sessions",
                expected=1,
                passed=0,
                findings=(finding("BGP005", "leaf-a1->10.0.0.1"),),
            ),
        )
    )

    rendered = report.render_human()

    assert rendered.startswith("Runtime verification: FAIL\n")
    assert "bgp-sessions: 0/1 passed [FAIL]" in rendered
    assert "Hint: Inspect the fabric link." in rendered
    assert rendered.endswith("Result: FAIL\n")
