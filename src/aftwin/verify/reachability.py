"""Normalize ping outcomes and verify reachability and isolation matrices."""

from collections.abc import Mapping, Sequence
from ipaddress import IPv4Address

from pydantic import BaseModel, ConfigDict, Field

from aftwin.compiler.expected_state import IsolationExpectation, ReachabilityExpectation
from aftwin.verify.report import (
    VerificationCategory,
    VerificationFinding,
    VerificationSection,
)


class PingOutcome(BaseModel):
    """Normalized result of one VRF-scoped endpoint ping command."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_node: str = Field(min_length=1)
    source_vrf: str = Field(min_length=1)
    destination_address: IPv4Address
    return_code: int = Field(ge=0)
    successful: bool
    detail: str = ""

    @property
    def key(self) -> tuple[str, str, IPv4Address]:
        """Return the expected-state lookup key."""
        return (self.source_node, self.source_vrf, self.destination_address)


def parse_ping_outcome(
    *,
    source_node: str,
    source_vrf: str,
    destination_address: IPv4Address,
    return_code: int,
    stdout: str = "",
    stderr: str = "",
) -> PingOutcome:
    """Normalize a bounded ping command result without relying on localized text."""
    output = stderr.strip() or stdout.strip()
    detail = output.splitlines()[-1] if output else f"ping exited with status {return_code}"
    return PingOutcome(
        source_node=source_node,
        source_vrf=source_vrf,
        destination_address=destination_address,
        return_code=return_code,
        successful=return_code == 0,
        detail=detail,
    )


def _outcome_index(
    observed: Sequence[PingOutcome],
) -> Mapping[tuple[str, str, IPv4Address], PingOutcome]:
    indexed: dict[tuple[str, str, IPv4Address], PingOutcome] = {}
    for outcome in observed:
        if outcome.key in indexed:
            raise ValueError(
                "duplicate ping outcome for "
                f"{outcome.source_node}:{outcome.source_vrf}->{outcome.destination_address}"
            )
        indexed[outcome.key] = outcome
    return indexed


def verify_reachability(
    expected: Sequence[ReachabilityExpectation],
    isolation: Sequence[IsolationExpectation],
    observed: Sequence[PingOutcome],
) -> tuple[VerificationSection, ...]:
    """Verify same-plane success and cross-plane failure using only fabric VRFs."""
    indexed = _outcome_index(observed)
    sections: list[VerificationSection] = []
    for plane in sorted({item.plane for item in expected}, key=lambda item: item.value):
        probes = sorted(
            (item for item in expected if item.plane is plane),
            key=lambda item: (item.source_node, item.destination_node),
        )
        findings: list[VerificationFinding] = []
        passed = 0
        for probe in probes:
            key = (probe.source_node, probe.source_vrf, probe.destination_address)
            outcome = indexed.get(key)
            target = f"{probe.source_node}:{probe.source_vrf}->{probe.destination_address}"
            if outcome is None:
                findings.append(
                    VerificationFinding(
                        rule_id="RCH001",
                        category=VerificationCategory.REACHABILITY,
                        target=target,
                        message="expected same-plane ping was not executed",
                        hint="Run the complete generated ping matrix from the endpoint VRF.",
                    )
                )
            elif not outcome.successful:
                findings.append(
                    VerificationFinding(
                        rule_id="RCH002",
                        category=VerificationCategory.REACHABILITY,
                        target=target,
                        message=f"same-plane ping failed: {outcome.detail}",
                        hint="Inspect endpoint VRF routes, leaf routes, and fabric link state.",
                    )
                )
            else:
                passed += 1
        sections.append(
            VerificationSection(
                name=f"reachability-plane-{plane.value}",
                expected=len(probes),
                passed=passed,
                findings=tuple(findings),
            )
        )

    isolation_findings: list[VerificationFinding] = []
    isolation_passed = 0
    isolation_total = 0
    for contract in sorted(
        isolation, key=lambda item: (item.source_plane.value, item.destination_plane.value)
    ):
        for source in contract.source_nodes:
            for destination in contract.blocked_endpoint_addresses:
                isolation_total += 1
                key = (source, contract.source_vrf, destination)
                outcome = indexed.get(key)
                target = f"{source}:{contract.source_vrf}->{destination}"
                if outcome is None:
                    isolation_findings.append(
                        VerificationFinding(
                            rule_id="ISO001",
                            category=VerificationCategory.ISOLATION,
                            target=target,
                            message="expected cross-plane isolation ping was not executed",
                            hint="Run every generated negative probe from its source-plane VRF.",
                        )
                    )
                elif outcome.return_code == 0:
                    isolation_findings.append(
                        VerificationFinding(
                            rule_id="ISO002",
                            category=VerificationCategory.ISOLATION,
                            target=target,
                            message="cross-plane ping unexpectedly succeeded",
                            hint=(
                                "Inspect route leaking, VRF interface membership, "
                                "and endpoint routes."
                            ),
                        )
                    )
                elif outcome.return_code == 1:
                    isolation_passed += 1
                else:
                    isolation_findings.append(
                        VerificationFinding(
                            rule_id="ISO003",
                            category=VerificationCategory.ISOLATION,
                            target=target,
                            message=(
                                "cross-plane probe was inconclusive: "
                                f"ping exited with status {outcome.return_code}"
                            ),
                            hint=(
                                "Confirm the endpoint setup, VRF, and ping executable before "
                                "accepting isolation."
                            ),
                        )
                    )
    sections.append(
        VerificationSection(
            name="cross-plane-isolation",
            expected=isolation_total,
            passed=isolation_passed,
            findings=tuple(isolation_findings),
        )
    )
    return tuple(sections)
