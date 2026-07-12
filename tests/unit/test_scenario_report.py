"""Tests for deterministic actionable scenario reports."""

import pytest
from pydantic import ValidationError

from aftwin.scenario.models import FailureTarget, ScenarioType
from aftwin.scenario.report import (
    ScenarioFinding,
    ScenarioPhase,
    ScenarioPhaseState,
    ScenarioReport,
)


def _state(phase: ScenarioPhase, *, failed: bool = False) -> ScenarioPhaseState:
    findings = (
        ScenarioFinding(
            rule_id="SCN001",
            target="gpu01->gpu03@fabric-a",
            cause="reachability probe failed during the injected failure",
            hint="Inspect the surviving leaf-to-spine path and BGP routes.",
        ),
    )
    return ScenarioPhaseState(
        phase=phase,
        expected_probes=2,
        passed_probes=1 if failed else 2,
        findings=findings if failed else (),
    )


def _report(states: tuple[ScenarioPhaseState, ...], *, restored: bool = True) -> ScenarioReport:
    return ScenarioReport(
        scenario="leaf-spine-link-failure",
        failure_type=ScenarioType.LINK_DOWN,
        target=FailureTarget(node="leaf-a1", interfaces=("eth1",)),
        restored=restored,
        states=states,
    )


def test_report_is_byte_stable_independent_of_state_order() -> None:
    states = tuple(_state(phase) for phase in ScenarioPhase)

    report = _report(states)
    reordered = _report(tuple(reversed(states)))

    assert report.to_json() == reordered.to_json()
    assert report.to_json().endswith("\n")
    assert [state.phase for state in report.states] == list(ScenarioPhase)
    assert report.passed


def test_failed_report_is_actionable_and_human_readable() -> None:
    states = tuple(
        _state(
            phase,
            failed=phase in {ScenarioPhase.DURING, ScenarioPhase.RECOVERY},
        )
        for phase in ScenarioPhase
    )
    report = _report(states, restored=False)

    rendered = report.render_human()

    assert not report.passed
    assert "Failure scenario leaf-spine-link-failure: FAIL" in rendered
    assert "during: 1/2 probes passed [FAIL]" in rendered
    assert "SCN001 gpu01->gpu03@fabric-a" in rendered
    assert "Hint: Inspect the surviving leaf-to-spine path and BGP routes." in rendered
    assert rendered.endswith("Restoration: FAIL\nResult: FAIL\n")


def test_failed_probe_count_requires_an_actionable_finding() -> None:
    with pytest.raises(ValidationError, match="actionable finding"):
        ScenarioPhaseState(
            phase=ScenarioPhase.DURING,
            expected_probes=2,
            passed_probes=1,
            findings=(),
        )


def test_report_requires_every_capture_phase_once() -> None:
    with pytest.raises(ValidationError, match="before, during, after, and recovery"):
        _report(
            (
                _state(ScenarioPhase.BEFORE),
                _state(ScenarioPhase.DURING),
                _state(ScenarioPhase.RECOVERY),
            )
        )


def test_failed_restoration_requires_recovery_evidence() -> None:
    with pytest.raises(ValidationError, match="actionable recovery evidence"):
        _report(tuple(_state(phase) for phase in ScenarioPhase), restored=False)
