"""Tests for FRR BGP JSON parsing and expected-state comparison."""

from ipaddress import IPv4Address

import pytest

from aftwin.compiler.expected_state import BgpAdjacency, BgpRouter
from aftwin.domain.enums import FabricPlane
from aftwin.verify.bgp import ObservedBgpRouter, parse_bgp_summary, verify_bgp


def adjacency() -> BgpAdjacency:
    return BgpAdjacency(
        plane=FabricPlane.A,
        leaf=BgpRouter(node="leaf-a1", address=IPv4Address("10.0.0.0"), asn=65101),
        spine=BgpRouter(node="spine-a1", address=IPv4Address("10.0.0.1"), asn=65001),
    )


def test_parse_realistic_frr_bgp_summary() -> None:
    state = parse_bgp_summary(
        "leaf-a1",
        {
            "ipv4Unicast": {
                "as": 65101,
                "peers": {
                    "10.0.0.1": {
                        "remoteAs": 65001,
                        "state": "Established",
                        "pfxRcd": 4,
                    }
                },
            }
        },
    )

    assert state.local_asn == 65101
    assert state.neighbors[0].address == "10.0.0.1"
    assert state.neighbors[0].remote_asn == 65001


def test_parse_bgp_summary_accepts_frr_key_variants_and_json_text() -> None:
    state = parse_bgp_summary(
        "leaf-a1",
        '{"localAS": "65101", "peers": '
        '{"10.0.0.1": {"remoteAS": "65001", "peerState": "Established"}}}',
    )

    assert state.local_asn == 65101
    assert state.neighbors[0].state == "Established"


def test_verify_bgp_passes_exact_bidirectional_session() -> None:
    leaf = parse_bgp_summary(
        "leaf-a1",
        {"as": 65101, "peers": {"10.0.0.1": {"remoteAs": 65001, "state": "Established"}}},
    )
    spine = parse_bgp_summary(
        "spine-a1",
        {"as": 65001, "peers": {"10.0.0.0": {"remoteAs": 65101, "state": "Established"}}},
    )

    section = verify_bgp((adjacency(),), {"spine-a1": spine, "leaf-a1": leaf})

    assert section.expected == 1
    assert section.passed == 1
    assert section.successful


def test_verify_bgp_reports_asn_state_missing_and_unexpected_neighbors() -> None:
    leaf = parse_bgp_summary(
        "leaf-a1",
        {
            "as": 65200,
            "peers": {
                "10.0.0.1": {"remoteAs": 65201, "state": "Active"},
                "192.0.2.1": {"remoteAs": 64512, "state": "Established"},
            },
        },
    )

    section = verify_bgp((adjacency(),), {"leaf-a1": leaf})

    assert section.passed == 0
    assert {finding.rule_id for finding in section.findings} == {
        "BGP001",
        "BGP002",
        "BGP004",
        "BGP005",
        "BGP006",
    }
    assert "show bgp summary json" in next(
        finding.hint for finding in section.findings if finding.rule_id == "BGP001"
    )


def test_parse_bgp_summary_rejects_missing_remote_asn() -> None:
    with pytest.raises(ValueError, match="no remote ASN"):
        parse_bgp_summary(
            "leaf-a1",
            {"as": 65101, "peers": {"10.0.0.1": {"state": "Established"}}},
        )


def test_observed_models_are_immutable() -> None:
    state = parse_bgp_summary("leaf-a1", {"as": 65101, "peers": {}})
    with pytest.raises(Exception):  # noqa: B017 - exact Pydantic exception is implementation detail
        state.local_asn = 1  # type: ignore[misc]
    assert isinstance(state, ObservedBgpRouter)
