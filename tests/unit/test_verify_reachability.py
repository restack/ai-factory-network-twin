"""Tests for fabric ping normalization and matrix verification."""

from ipaddress import IPv4Address, IPv4Network

import pytest

from aftwin.compiler.expected_state import IsolationExpectation, ReachabilityExpectation
from aftwin.domain.enums import FabricPlane
from aftwin.verify.reachability import PingOutcome, parse_ping_outcome, verify_reachability


def reachability() -> ReachabilityExpectation:
    return ReachabilityExpectation(
        plane=FabricPlane.A,
        source_node="gpu01",
        source_interface="eth1",
        source_vrf="fabric-a",
        source_address=IPv4Address("10.20.0.1"),
        destination_node="gpu02",
        destination_address=IPv4Address("10.20.0.3"),
    )


def isolation() -> IsolationExpectation:
    return IsolationExpectation(
        source_plane=FabricPlane.A,
        source_vrf="fabric-a",
        destination_plane=FabricPlane.B,
        source_nodes=("gpu01",),
        blocked_endpoint_addresses=(IPv4Address("10.21.0.1"),),
        forbidden_route_pools=(IPv4Network("10.21.0.0/24"),),
    )


def outcome(destination: str, successful: bool) -> PingOutcome:
    return PingOutcome(
        source_node="gpu01",
        source_vrf="fabric-a",
        destination_address=IPv4Address(destination),
        return_code=0 if successful else 1,
        successful=successful,
        detail="1 packets transmitted, 1 received" if successful else "100% packet loss",
    )


def test_parse_ping_outcome_uses_exit_status_and_bounded_detail() -> None:
    result = parse_ping_outcome(
        source_node="gpu01",
        source_vrf="fabric-a",
        destination_address=IPv4Address("10.20.0.3"),
        return_code=1,
        stdout="PING 10.20.0.3\n1 packets transmitted, 0 received, 100% packet loss\n",
    )

    assert not result.successful
    assert result.detail == "1 packets transmitted, 0 received, 100% packet loss"


def test_verify_reachability_passes_positive_and_negative_matrices() -> None:
    sections = verify_reachability(
        (reachability(),),
        (isolation(),),
        (outcome("10.20.0.3", True), outcome("10.21.0.1", False)),
    )

    assert len(sections) == 2
    assert all(section.successful for section in sections)


def test_verify_reachability_reports_failure_leak_and_missing_probes() -> None:
    sections = verify_reachability(
        (reachability(),),
        (isolation(),),
        (outcome("10.20.0.3", False), outcome("10.21.0.1", True)),
    )

    assert {finding.rule_id for section in sections for finding in section.findings} == {
        "ISO002",
        "RCH002",
    }

    missing = verify_reachability((reachability(),), (isolation(),), ())
    assert {finding.rule_id for section in missing for finding in section.findings} == {
        "ISO001",
        "RCH001",
    }


def test_duplicate_ping_outcomes_are_rejected() -> None:
    duplicate = outcome("10.20.0.3", True)
    with pytest.raises(ValueError, match="duplicate ping outcome"):
        verify_reachability((reachability(),), (), (duplicate, duplicate))


def test_isolation_rejects_infrastructure_command_errors() -> None:
    inconclusive = outcome("10.21.0.1", False).model_copy(update={"return_code": 127})

    sections = verify_reachability((), (isolation(),), (inconclusive,))

    assert sections[0].findings[0].rule_id == "ISO003"
