"""Deterministic models and rendering for static validation findings."""

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(StrEnum):
    """Stable severity levels exposed by the policy API."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


_SEVERITY_ORDER = {
    Severity.ERROR: 0,
    Severity.WARNING: 1,
    Severity.INFO: 2,
}


class Finding(BaseModel):
    """One actionable policy result with a stable rule identifier."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    message: str = Field(min_length=1)
    hint: str = Field(min_length=1)
    severity: Severity

    def as_dict(self) -> dict[str, str]:
        """Return the stable public representation of this finding."""
        return {
            "rule_id": self.rule_id,
            "target": self.target,
            "message": self.message,
            "hint": self.hint,
            "severity": self.severity.value,
        }


def _finding_sort_key(finding: Finding) -> tuple[int, str, str, str, str]:
    return (
        _SEVERITY_ORDER[finding.severity],
        finding.rule_id,
        finding.target,
        finding.message,
        finding.hint,
    )


class ValidationReport(BaseModel):
    """An immutable, deterministically ordered collection of findings."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    findings: tuple[Finding, ...] = ()

    @field_validator("findings")
    @classmethod
    def sort_findings(cls, findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
        """Canonicalize report order independently of rule execution order."""
        return tuple(sorted(findings, key=_finding_sort_key))

    @property
    def error_count(self) -> int:
        """Return the number of findings that make validation fail."""
        return sum(finding.severity is Severity.ERROR for finding in self.findings)

    @property
    def warning_count(self) -> int:
        """Return the number of non-fatal warning findings."""
        return sum(finding.severity is Severity.WARNING for finding in self.findings)

    @property
    def info_count(self) -> int:
        """Return the number of informational findings."""
        return sum(finding.severity is Severity.INFO for finding in self.findings)

    @property
    def passed(self) -> bool:
        """Validation passes when it contains no error findings."""
        return self.error_count == 0

    @property
    def failed(self) -> bool:
        """Validation fails when at least one error finding exists."""
        return not self.passed

    def as_dict(self) -> dict[str, Any]:
        """Return a deterministic machine-readable report."""
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "findings": [finding.as_dict() for finding in self.findings],
        }

    def to_json(self) -> str:
        """Render canonical, newline-terminated JSON for files and snapshots."""
        return (
            json.dumps(
                self.as_dict(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        )

    def render_human(self) -> str:
        """Render a concise deterministic console report."""
        status = "PASS" if self.passed else "FAIL"
        lines = [
            f"Static validation: {status}",
            (
                f"Findings: {self.error_count} error(s), "
                f"{self.warning_count} warning(s), {self.info_count} info"
            ),
        ]
        for finding in self.findings:
            lines.append(
                f"[{finding.severity.value.upper()}] {finding.rule_id} "
                f"{finding.target}: {finding.message}"
            )
            lines.append(f"  Hint: {finding.hint}")
        return "\n".join(lines) + "\n"
