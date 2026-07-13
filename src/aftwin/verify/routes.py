"""Parse FRR route JSON and verify protocol, ECMP, and plane isolation."""

import json
from collections.abc import Mapping, Sequence
from ipaddress import IPv4Address, IPv4Network
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from aftwin.compiler.expected_state import IsolationExpectation, RouterPrefixExpectation
from aftwin.verify.report import (
    VerificationCategory,
    VerificationFinding,
    VerificationSection,
)


class ObservedRoute(BaseModel):
    """One normalized installed route candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    prefix: IPv4Network
    protocol: str = Field(min_length=1)
    next_hops: tuple[IPv4Address, ...] = ()


class ObservedRouteTable(BaseModel):
    """Normalized installed IPv4 routes for one router."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    router: str = Field(min_length=1)
    routes: tuple[ObservedRoute, ...]


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    return cast(Mapping[str, Any], value)


def parse_route_table(router: str, payload: str | Mapping[str, Any]) -> ObservedRouteTable:
    """Normalize FRR ``show ip route json`` output, keeping installed candidates."""
    raw: object = json.loads(payload) if isinstance(payload, str) else payload
    root = _mapping(raw, f"route table for {router}")
    routes: list[ObservedRoute] = []
    for prefix_text, candidates_raw in sorted(root.items()):
        if not isinstance(candidates_raw, list):
            raise ValueError(f"route candidates for {router}:{prefix_text} must be an array")
        for candidate_raw in cast(list[object], candidates_raw):
            candidate = _mapping(candidate_raw, f"route {router}:{prefix_text}")
            # FRR may omit these booleans; explicit false means the route is not in the RIB.
            if candidate.get("selected") is False or candidate.get("installed") is False:
                continue
            protocol_raw = candidate.get("protocol")
            if not isinstance(protocol_raw, str) or not protocol_raw:
                raise ValueError(f"route {router}:{prefix_text} has no protocol")
            next_hops_raw = candidate.get("nexthops", [])
            if not isinstance(next_hops_raw, list):
                raise ValueError(f"nexthops for {router}:{prefix_text} must be an array")
            next_hops: set[IPv4Address] = set()
            for hop_raw in cast(list[object], next_hops_raw):
                hop = _mapping(hop_raw, f"next hop for {router}:{prefix_text}")
                if hop.get("active") is False:
                    continue
                address = hop.get("ip", hop.get("gateway"))
                if isinstance(address, str):
                    next_hops.add(IPv4Address(address))
            routes.append(
                ObservedRoute(
                    prefix=IPv4Network(prefix_text),
                    protocol=protocol_raw.casefold(),
                    next_hops=tuple(sorted(next_hops, key=int)),
                )
            )
    return ObservedRouteTable(
        router=router,
        routes=tuple(
            sorted(
                routes,
                key=lambda route: (
                    int(route.prefix.network_address),
                    route.prefix.prefixlen,
                    route.protocol,
                ),
            )
        ),
    )


def verify_routes(
    expected: Sequence[RouterPrefixExpectation],
    isolation: Sequence[IsolationExpectation],
    observed: Mapping[str, ObservedRouteTable],
) -> VerificationSection:
    """Verify expected routes and reject routes from the opposite plane's pools."""
    findings: list[VerificationFinding] = []
    passed = 0
    missing_router_reported: set[str] = set()
    for route_expected in sorted(expected, key=lambda item: (item.router, str(item.prefix))):
        target = f"{route_expected.router}:{route_expected.prefix}"
        table = observed.get(route_expected.router)
        if table is None:
            if route_expected.router not in missing_router_reported:
                findings.append(
                    VerificationFinding(
                        rule_id="RTE001",
                        category=VerificationCategory.ROUTES,
                        target=route_expected.router,
                        message="route table was not collected",
                        hint=(
                            f"Confirm {route_expected.router} is running and collect "
                            "'show ip route json'."
                        ),
                    )
                )
                missing_router_reported.add(route_expected.router)
            continue
        prefix_routes = [route for route in table.routes if route.prefix == route_expected.prefix]
        if not prefix_routes:
            findings.append(
                VerificationFinding(
                    rule_id="RTE002",
                    category=VerificationCategory.ROUTES,
                    target=target,
                    message="expected prefix is absent from the RIB",
                    hint=(
                        "Inspect BGP advertisements, adjacency state, and the attached "
                        "endpoint link."
                    ),
                )
            )
            continue
        protocol_routes = [
            route for route in prefix_routes if route.protocol == route_expected.protocol
        ]
        if not protocol_routes:
            observed_protocols = ", ".join(sorted({route.protocol for route in prefix_routes}))
            findings.append(
                VerificationFinding(
                    rule_id="RTE003",
                    category=VerificationCategory.ROUTES,
                    target=target,
                    message=(
                        f"protocol is {observed_protocols}, expected {route_expected.protocol}"
                    ),
                    hint="Check whether the prefix is attached locally or learned through BGP.",
                )
            )
            continue
        next_hop_count = max(len(route.next_hops) for route in protocol_routes)
        if next_hop_count < route_expected.min_next_hops:
            findings.append(
                VerificationFinding(
                    rule_id="RTE004",
                    category=VerificationCategory.ROUTES,
                    target=target,
                    message=(
                        f"route has {next_hop_count} active next hop(s), "
                        f"expected at least {route_expected.min_next_hops}"
                    ),
                    hint=(
                        "Inspect missing spine paths, BGP multipath settings, and interface state."
                    ),
                )
            )
            continue
        passed += 1

    forbidden_by_plane = {
        expectation.source_plane: expectation.forbidden_route_pools for expectation in isolation
    }
    router_planes = {item.router: item.plane for item in expected}
    for router, table in sorted(observed.items()):
        plane = router_planes.get(router)
        if plane is None:
            continue
        forbidden = forbidden_by_plane.get(plane, ())
        for route in table.routes:
            # The unscoped FRR RIB also contains the container management
            # default route. Isolation concerns control-plane routes learned
            # from the opposite fabric plane, not local kernel/static routes.
            if route.protocol != "bgp":
                continue
            pool = next((pool for pool in forbidden if route.prefix.overlaps(pool)), None)
            if pool is not None:
                findings.append(
                    VerificationFinding(
                        rule_id="RTE005",
                        category=VerificationCategory.ROUTES,
                        target=f"{router}:{route.prefix}",
                        message=(
                            f"route overlapping forbidden cross-plane pool {pool} is installed"
                        ),
                        hint=(
                            "Remove route leaking between Plane A and Plane B and "
                            "inspect VRF scope."
                        ),
                    )
                )
    return VerificationSection(
        name="routes",
        expected=len(expected),
        passed=passed,
        findings=tuple(findings),
    )
