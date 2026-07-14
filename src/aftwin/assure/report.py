"""Deterministic pre-deployment assurance findings and reporting.

Assurance findings are derived evidence about generated configuration; they
carry their evidence source and fidelity claim so they can never be confused
with authoritative policy findings or observed runtime state.
"""

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssuranceCategory(StrEnum):
    """Stable pre-deployment assurance categories."""

    PARSE = "parse"
    BGP = "bgp"
    FORWARDING = "forwarding"
    ROUTES = "routes"
    ISOLATION = "isolation"


class AssuranceFinding(BaseModel):
    """One actionable derived-evidence mismatch."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    rule_id: str = Field(min_length=1)
    category: AssuranceCategory
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


def _finding_key(finding: AssuranceFinding) -> tuple[str, str, str, str, str]:
    return (
        finding.rule_id,
        finding.target,
        finding.message,
        finding.hint,
        finding.category.value,
    )


class AssuranceSection(BaseModel):
    """Counts and failures for one admitted assurance question."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(min_length=1)
    expected: int = Field(ge=0)
    passed: int = Field(ge=0)
    findings: tuple[AssuranceFinding, ...] = ()

    @field_validator("findings")
    @classmethod
    def sort_findings(cls, findings: tuple[AssuranceFinding, ...]) -> tuple[AssuranceFinding, ...]:
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


class AssuranceReport(BaseModel):
    """Canonical aggregate pre-deployment assurance report."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    build_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(min_length=1)
    evidence_source: Literal["batfish"] = "batfish"
    fidelity_claim: Literal["generated-configuration"] = "generated-configuration"
    syntax_supported: bool
    sections: tuple[AssuranceSection, ...]

    @field_validator("sections")
    @classmethod
    def sort_sections(cls, sections: tuple[AssuranceSection, ...]) -> tuple[AssuranceSection, ...]:
        """Keep report serialization independent of question execution order."""
        return tuple(sorted(sections, key=lambda section: section.name))

    @property
    def findings(self) -> tuple[AssuranceFinding, ...]:
        """Return all findings in canonical order."""
        return tuple(
            sorted(
                (finding for section in self.sections for finding in section.findings),
                key=_finding_key,
            )
        )

    @property
    def passed(self) -> bool:
        """Assurance passes only with supported syntax and passing sections."""
        return self.syntax_supported and all(section.successful for section in self.sections)

    def as_dict(self) -> dict[str, Any]:
        """Return deterministic machine-readable report data."""
        return {
            "build_hash": self.build_hash,
            "source_revision": self.source_revision,
            "evidence_source": self.evidence_source,
            "fidelity_claim": self.fidelity_claim,
            "syntax_supported": self.syntax_supported,
            "passed": self.passed,
            "finding_count": len(self.findings),
            "sections": [section.as_dict() for section in self.sections],
        }

    def to_json(self) -> str:
        """Render canonical newline-terminated JSON."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"

    def render_human(self) -> str:
        """Render a concise deterministic operator report."""
        if not self.syntax_supported:
            headline = "CAPABILITY DISABLED (unsupported syntax)"
        elif self.passed:
            headline = "PASS"
        else:
            headline = "FAIL"
        lines = [f"Pre-deployment assurance (batfish): {headline}"]
        for section in self.sections:
            status = "PASS" if section.successful else "FAIL"
            lines.append(f"{section.name}: {section.passed}/{section.expected} passed [{status}]")
        for finding in self.findings:
            lines.append(f"[ERROR] {finding.rule_id} {finding.target}: {finding.message}")
            lines.append(f"  Hint: {finding.hint}")
        lines.append("Result: " + ("PASS" if self.passed else "FAIL"))
        return "\n".join(lines) + "\n"
