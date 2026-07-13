"""Deterministic and actionable failure-scenario evidence reports."""

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aftwin.scenario.models import FailureTarget, ScenarioType


class ScenarioPhase(StrEnum):
    """Ordered evidence capture points across a reversible failure."""

    BEFORE = "before"
    DURING = "during"
    AFTER = "after"
    RECOVERY = "recovery"


PHASE_ORDER = {
    ScenarioPhase.BEFORE: 0,
    ScenarioPhase.DURING: 1,
    ScenarioPhase.AFTER: 2,
    ScenarioPhase.RECOVERY: 3,
}


class ScenarioReportModel(BaseModel):
    """Immutable base for scenario evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ScenarioFinding(ScenarioReportModel):
    """One actionable mismatch found during a scenario phase."""

    rule_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    cause: str = Field(min_length=1)
    hint: str = Field(min_length=1)

    def as_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "target": self.target,
            "cause": self.cause,
            "hint": self.hint,
        }


def _finding_key(finding: ScenarioFinding) -> tuple[str, str, str, str]:
    return (finding.rule_id, finding.target, finding.cause, finding.hint)


class ScenarioPhaseState(ScenarioReportModel):
    """Probe results and findings captured at one scenario phase."""

    phase: ScenarioPhase
    expected_probes: int = Field(ge=0)
    passed_probes: int = Field(ge=0)
    findings: tuple[ScenarioFinding, ...] = ()

    @field_validator("findings")
    @classmethod
    def canonicalize_findings(
        cls, findings: tuple[ScenarioFinding, ...]
    ) -> tuple[ScenarioFinding, ...]:
        return tuple(sorted(findings, key=_finding_key))

    @model_validator(mode="after")
    def require_actionable_failure(self) -> "ScenarioPhaseState":
        if self.passed_probes > self.expected_probes:
            raise ValueError("passed probes cannot exceed expected probes")
        if self.passed_probes != self.expected_probes and not self.findings:
            raise ValueError("a failed phase requires at least one actionable finding")
        return self

    @property
    def successful(self) -> bool:
        return self.passed_probes == self.expected_probes and not self.findings

    def as_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "expected_probes": self.expected_probes,
            "passed_probes": self.passed_probes,
            "successful": self.successful,
            "findings": [finding.as_dict() for finding in self.findings],
        }


class ScenarioReport(ScenarioReportModel):
    """Canonical before/during/after/recovery evidence for one scenario."""

    schema_version: Literal[1] = 1
    scenario: str = Field(min_length=1)
    scenario_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(min_length=1)
    failure_type: ScenarioType
    target: FailureTarget
    restored: bool
    states: tuple[ScenarioPhaseState, ...]

    @field_validator("states")
    @classmethod
    def canonicalize_states(
        cls, states: tuple[ScenarioPhaseState, ...]
    ) -> tuple[ScenarioPhaseState, ...]:
        phases = [state.phase for state in states]
        required = set(ScenarioPhase)
        if len(states) != len(required) or set(phases) != required:
            raise ValueError("scenario report requires before, during, after, and recovery states")
        return tuple(sorted(states, key=lambda state: PHASE_ORDER[state.phase]))

    @model_validator(mode="after")
    def require_recovery_evidence_for_failed_restoration(self) -> "ScenarioReport":
        recovery = next(state for state in self.states if state.phase is ScenarioPhase.RECOVERY)
        if not self.restored and recovery.successful:
            raise ValueError("failed restoration requires actionable recovery evidence")
        return self

    @property
    def findings(self) -> tuple[ScenarioFinding, ...]:
        return tuple(
            sorted(
                (finding for state in self.states for finding in state.findings),
                key=_finding_key,
            )
        )

    @property
    def passed(self) -> bool:
        return self.restored and all(state.successful for state in self.states)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "scenario": self.scenario,
            "scenario_revision": self.scenario_revision,
            "build_hash": self.build_hash,
            "source_revision": self.source_revision,
            "failure_type": self.failure_type.value,
            "target": {
                "node": self.target.node,
                "interfaces": list(self.target.interfaces),
            },
            "restored": self.restored,
            "passed": self.passed,
            "finding_count": len(self.findings),
            "states": [state.as_dict() for state in self.states],
        }

    def to_json(self) -> str:
        """Render canonical newline-terminated JSON."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"

    def render_human(self) -> str:
        """Render a concise operator report including causes and recovery status."""
        lines = [f"Failure scenario {self.scenario}: " + ("PASS" if self.passed else "FAIL")]
        interfaces = ",".join(self.target.interfaces) or "all"
        lines.append(
            f"Failure: {self.failure_type.value} target={self.target.node} interfaces={interfaces}"
        )
        for state in self.states:
            status = "PASS" if state.successful else "FAIL"
            lines.append(
                f"{state.phase.value}: {state.passed_probes}/{state.expected_probes} "
                f"probes passed [{status}]"
            )
            for finding in state.findings:
                lines.append(f"[ERROR] {finding.rule_id} {finding.target}: {finding.cause}")
                lines.append(f"  Hint: {finding.hint}")
        lines.append("Restoration: " + ("PASS" if self.restored else "FAIL"))
        lines.append("Result: " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines) + "\n"
