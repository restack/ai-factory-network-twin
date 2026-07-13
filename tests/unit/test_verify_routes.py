"""Tests for FRR route parsing and runtime route verification."""

from ipaddress import IPv4Network

from aftwin.compiler.expected_state import IsolationExpectation, RouterPrefixExpectation
from aftwin.domain.enums import FabricPlane
from aftwin.verify.routes import parse_route_table, verify_routes


def route_expectation(*, min_next_hops: int = 2) -> RouterPrefixExpectation:
    return RouterPrefixExpectation(
        router="leaf-a1",
        plane=FabricPlane.A,
        prefix=IPv4Network("10.20.0.2/31"),
        protocol="bgp",
        min_next_hops=min_next_hops,
        endpoint_node="gpu02",
        attached_leaf="leaf-a2",
    )


def isolation_expectation() -> IsolationExpectation:
    return IsolationExpectation(
        source_plane=FabricPlane.A,
        source_vrf="fabric-a",
        destination_plane=FabricPlane.B,
        source_nodes=("gpu01",),
        blocked_endpoint_addresses=(),
        forbidden_route_pools=(IPv4Network("10.21.0.0/24"),),
    )


def test_parse_route_table_keeps_installed_routes_and_active_unique_next_hops() -> None:
    table = parse_route_table(
        "leaf-a1",
        {
            "10.20.0.2/31": [
                {
                    "protocol": "bgp",
                    "selected": True,
                    "installed": True,
                    "nexthops": [
                        {"ip": "10.0.0.1", "active": True},
                        {"ip": "10.0.0.3", "active": True},
                        {"ip": "10.0.0.3", "active": True},
                    ],
                },
                {"protocol": "static", "selected": False, "nexthops": []},
            ]
        },
    )

    assert len(table.routes) == 1
    assert tuple(map(str, table.routes[0].next_hops)) == ("10.0.0.1", "10.0.0.3")


def test_verify_routes_passes_protocol_and_ecmp_contract() -> None:
    table = parse_route_table(
        "leaf-a1",
        {
            "10.20.0.2/31": [
                {
                    "protocol": "bgp",
                    "nexthops": [{"ip": "10.0.0.1"}, {"ip": "10.0.0.3"}],
                }
            ]
        },
    )

    section = verify_routes((route_expectation(),), (isolation_expectation(),), {"leaf-a1": table})

    assert section.successful
    assert section.passed == 1


def test_verify_routes_reports_protocol_ecmp_missing_router_and_plane_leak() -> None:
    protocol_table = parse_route_table(
        "leaf-a1",
        {
            "10.20.0.2/31": [{"protocol": "connected", "nexthops": []}],
            "10.21.0.4/31": [{"protocol": "bgp", "nexthops": [{"ip": "10.0.0.1"}]}],
        },
    )
    expected = (
        route_expectation(),
        route_expectation(min_next_hops=1).model_copy(update={"router": "leaf-a2"}),
    )

    section = verify_routes(expected, (isolation_expectation(),), {"leaf-a1": protocol_table})

    assert section.passed == 0
    assert {finding.rule_id for finding in section.findings} == {"RTE001", "RTE003", "RTE005"}


def test_verify_routes_reports_insufficient_ecmp() -> None:
    table = parse_route_table(
        "leaf-a1",
        {"10.20.0.2/31": [{"protocol": "bgp", "nexthops": [{"ip": "10.0.0.1"}]}]},
    )

    section = verify_routes((route_expectation(),), (isolation_expectation(),), {"leaf-a1": table})

    finding = section.findings[0]
    assert finding.rule_id == "RTE004"
    assert "expected at least 2" in finding.message


def test_verify_routes_rejects_aggregate_and_default_routes_overlapping_forbidden_pool() -> None:
    table = parse_route_table(
        "leaf-a1",
        {
            "0.0.0.0/0": [{"protocol": "bgp", "nexthops": [{"ip": "10.0.0.1"}]}],
            "10.0.0.0/8": [{"protocol": "bgp", "nexthops": [{"ip": "10.0.0.1"}]}],
            "10.20.0.2/31": [
                {
                    "protocol": "bgp",
                    "nexthops": [{"ip": "10.0.0.1"}, {"ip": "10.0.0.3"}],
                }
            ],
            "192.0.2.0/24": [{"protocol": "bgp", "nexthops": [{"ip": "10.0.0.1"}]}],
        },
    )

    section = verify_routes((route_expectation(),), (isolation_expectation(),), {"leaf-a1": table})

    leak_targets = {finding.target for finding in section.findings if finding.rule_id == "RTE005"}
    assert section.passed == 1
    assert leak_targets == {"leaf-a1:0.0.0.0/0", "leaf-a1:10.0.0.0/8"}


def test_verify_routes_allows_non_bgp_management_default_route() -> None:
    table = parse_route_table(
        "leaf-a1",
        {
            "0.0.0.0/0": [{"protocol": "kernel", "nexthops": [{"ip": "172.30.30.1"}]}],
            "10.20.0.2/31": [
                {
                    "protocol": "bgp",
                    "nexthops": [{"ip": "10.0.0.1"}, {"ip": "10.0.0.3"}],
                }
            ],
        },
    )

    section = verify_routes((route_expectation(),), (isolation_expectation(),), {"leaf-a1": table})

    assert section.successful
