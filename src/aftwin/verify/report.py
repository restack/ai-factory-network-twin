"""Deterministic runtime verification findings and reporting."""

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VerificationCategory(StrEnum):
    """Stable runtime verification categories."""

    BGP = "bgp"
    ROUTES = "routes"
    REACHABILITY = "reachability"
    ISOLATION = "isolation"


class VerificationFinding(BaseModel):
    """One actionable expected-versus-observed mismatch."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: str = Field(min_length=1)
    category: VerificationCategory
    target: str = Field(min_length=1)
    message: str = Field(min_length=1)
    hint: str = Field(min_length=1)

    def as_dict(self) -> dict[str, str]:
        """Return the stable public representation."""
        return {
            "rule_id": self.rule_id,
            "category": self.category.value,
            "target": self.target,
            "message": self.message,
            "hint": self.hint,
        }


def _finding_key(finding: VerificationFinding) -> tuple[str, str, str, str, str]:
    return (
        finding.rule_id,
        finding.target,
        finding.message,
        finding.hint,
        finding.category.value,
    )


class VerificationSection(BaseModel):
    """Counts and failures for one independently measured runtime property."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    expected: int = Field(ge=0)
    passed: int = Field(ge=0)
    findings: tuple[VerificationFinding, ...] = ()

    @field_validator("findings")
    @classmethod
    def sort_findings(
        cls, findings: tuple[VerificationFinding, ...]
    ) -> tuple[VerificationFinding, ...]:
        """Canonicalize failures independently of collection order."""
        return tuple(sorted(findings, key=_finding_key))

    @property
    def successful(self) -> bool:
        """A section passes only when every check and invariant passes."""
        return self.passed == self.expected and not self.findings

    def as_dict(self) -> dict[str, Any]:
        """Return deterministic machine-readable section data."""
        return {
            "name": self.name,
            "expected": self.expected,
            "passed": self.passed,
            "successful": self.successful,
            "findings": [finding.as_dict() for finding in self.findings],
        }


class VerificationReport(BaseModel):
    """Canonical aggregate runtime verification report."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sections: tuple[VerificationSection, ...]

    @field_validator("sections")
    @classmethod
    def sort_sections(
        cls, sections: tuple[VerificationSection, ...]
    ) -> tuple[VerificationSection, ...]:
        """Keep report serialization independent of verifier execution order."""
        return tuple(sorted(sections, key=lambda section: section.name))

    @property
    def findings(self) -> tuple[VerificationFinding, ...]:
        """Return all findings in canonical order."""
        return tuple(
            sorted(
                (finding for section in self.sections for finding in section.findings),
                key=_finding_key,
            )
        )

    @property
    def passed(self) -> bool:
        """Runtime verification passes only when every section passes."""
        return all(section.successful for section in self.sections)

    def as_dict(self) -> dict[str, Any]:
        """Return deterministic machine-readable report data."""
        return {
            "passed": self.passed,
            "finding_count": len(self.findings),
            "sections": [section.as_dict() for section in self.sections],
        }

    def to_json(self) -> str:
        """Render canonical newline-terminated JSON."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"

    def render_human(self) -> str:
        """Render a concise deterministic operator report."""
        lines = ["Runtime verification: " + ("PASS" if self.passed else "FAIL")]
        for section in self.sections:
            status = "PASS" if section.successful else "FAIL"
            lines.append(f"{section.name}: {section.passed}/{section.expected} passed [{status}]")
        for finding in self.findings:
            lines.append(f"[ERROR] {finding.rule_id} {finding.target}: {finding.message}")
            lines.append(f"  Hint: {finding.hint}")
        lines.append("Result: " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines) + "\n"
