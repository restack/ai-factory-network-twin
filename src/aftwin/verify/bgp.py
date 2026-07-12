"""Parse FRR BGP summary JSON and compare it with expected adjacencies."""

import json
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from aftwin.compiler.expected_state import BgpAdjacency
from aftwin.verify.report import (
    VerificationCategory,
    VerificationFinding,
    VerificationSection,
)


class ObservedBgpNeighbor(BaseModel):
    """Normalized FRR neighbor state."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    address: str = Field(min_length=1)
    remote_asn: int = Field(ge=1, le=4_294_967_295)
    state: str = Field(min_length=1)


class ObservedBgpRouter(BaseModel):
    """Normalized output of ``show bgp summary json`` for one router."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    router: str = Field(min_length=1)
    local_asn: int = Field(ge=1, le=4_294_967_295)
    neighbors: tuple[ObservedBgpNeighbor, ...]


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{context} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{context} must be an integer") from exc


def parse_bgp_summary(router: str, payload: str | Mapping[str, Any]) -> ObservedBgpRouter:
    """Normalize realistic FRR ``show bgp summary json`` variants."""
    raw: object = json.loads(payload) if isinstance(payload, str) else payload
    root = _mapping(raw, f"BGP summary for {router}")
    afi_raw = root.get("ipv4Unicast", root)
    afi = _mapping(afi_raw, f"IPv4 unicast BGP summary for {router}")
    local_raw = afi.get("as", afi.get("localAS", root.get("localAS")))
    if local_raw is None:
        raise ValueError(f"BGP summary for {router} has no local ASN")
    peers = _mapping(afi.get("peers", {}), f"BGP peers for {router}")
    neighbors: list[ObservedBgpNeighbor] = []
    for address, peer_raw in sorted(peers.items()):
        peer = _mapping(peer_raw, f"BGP peer {router}:{address}")
        remote_raw = peer.get("remoteAs", peer.get("remoteAS"))
        if remote_raw is None:
            raise ValueError(f"BGP peer {router}:{address} has no remote ASN")
        state_raw = peer.get("state", peer.get("peerState"))
        if not isinstance(state_raw, str) or not state_raw:
            raise ValueError(f"BGP peer {router}:{address} has no state")
        neighbors.append(
            ObservedBgpNeighbor(
                address=str(address),
                remote_asn=_integer(remote_raw, f"remote ASN for {router}:{address}"),
                state=state_raw,
            )
        )
    return ObservedBgpRouter(
        router=router,
        local_asn=_integer(local_raw, f"local ASN for {router}"),
        neighbors=tuple(neighbors),
    )


def verify_bgp(
    expected: Sequence[BgpAdjacency],
    observed: Mapping[str, ObservedBgpRouter],
) -> VerificationSection:
    """Verify exact expected neighbors, ASNs, and Established state."""
    expected_peers: dict[str, dict[str, int]] = {}
    local_asns: dict[str, int] = {}
    checks: list[tuple[int, str, str, int, int]] = []
    for adjacency_index, adjacency in enumerate(expected):
        for local, remote in ((adjacency.leaf, adjacency.spine), (adjacency.spine, adjacency.leaf)):
            address = str(remote.address)
            expected_peers.setdefault(local.node, {})[address] = remote.asn
            local_asns[local.node] = local.asn
            checks.append((adjacency_index, local.node, address, local.asn, remote.asn))

    findings: list[VerificationFinding] = []
    adjacency_passed = {index: True for index in range(len(expected))}
    missing_router_reported: set[str] = set()
    local_asn_reported: set[str] = set()
    for adjacency_index, router, address, local_asn, remote_asn in sorted(checks):
        state = observed.get(router)
        target = f"{router}->{address}"
        if state is None:
            adjacency_passed[adjacency_index] = False
            if router not in missing_router_reported:
                findings.append(
                    VerificationFinding(
                        rule_id="BGP001",
                        category=VerificationCategory.BGP,
                        target=router,
                        message="BGP summary was not collected",
                        hint=f"Confirm {router} is running and collect 'show bgp summary json'.",
                    )
                )
                missing_router_reported.add(router)
            continue
        neighbor = {item.address: item for item in state.neighbors}.get(address)
        check_passed = True
        if state.local_asn != local_asn:
            if router not in local_asn_reported:
                findings.append(
                    VerificationFinding(
                        rule_id="BGP002",
                        category=VerificationCategory.BGP,
                        target=router,
                        message=f"local ASN {state.local_asn} does not match expected {local_asn}",
                        hint=(
                            "Regenerate the router configuration and inspect the active "
                            "FRR BGP process."
                        ),
                    )
                )
                local_asn_reported.add(router)
            check_passed = False
        if neighbor is None:
            adjacency_passed[adjacency_index] = False
            findings.append(
                VerificationFinding(
                    rule_id="BGP003",
                    category=VerificationCategory.BGP,
                    target=target,
                    message="expected BGP neighbor is absent",
                    hint="Check interface addressing and the rendered neighbor configuration.",
                )
            )
            continue
        if neighbor.remote_asn != remote_asn:
            findings.append(
                VerificationFinding(
                    rule_id="BGP004",
                    category=VerificationCategory.BGP,
                    target=target,
                    message=(
                        f"remote ASN {neighbor.remote_asn} does not match expected {remote_asn}"
                    ),
                    hint="Correct the peer ASN on both ends of the adjacency.",
                )
            )
            check_passed = False
        if neighbor.state.casefold() != "established":
            findings.append(
                VerificationFinding(
                    rule_id="BGP005",
                    category=VerificationCategory.BGP,
                    target=target,
                    message=f"BGP state is {neighbor.state}, expected Established",
                    hint="Inspect link state, addressing, FRR logs, and neighbor configuration.",
                )
            )
            check_passed = False
        if check_passed:
            continue
        adjacency_passed[adjacency_index] = False

    for router, state in sorted(observed.items()):
        allowed = expected_peers.get(router, {})
        for neighbor in state.neighbors:
            if neighbor.address not in allowed:
                findings.append(
                    VerificationFinding(
                        rule_id="BGP006",
                        category=VerificationCategory.BGP,
                        target=f"{router}->{neighbor.address}",
                        message="unexpected BGP neighbor exists",
                        hint="Remove the neighbor or add it to the authoritative topology.",
                    )
                )
    return VerificationSection(
        name="bgp-sessions",
        expected=len(expected),
        passed=sum(adjacency_passed.values()),
        findings=tuple(findings),
    )
