"""Deterministic expected runtime state generation."""

from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aftwin.domain.enums import FabricPlane, LinkKind, NodeRole
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node
from aftwin.policy.profile import PolicyProfile


class ExpectedStateModel(BaseModel):
    """Strict immutable base for generated expected-state records."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BgpRouter(ExpectedStateModel):
    """One side of an expected BGP adjacency."""

    node: str
    address: IPv4Address
    asn: int = Field(ge=1, le=4_294_967_295)


class BgpAdjacency(ExpectedStateModel):
    """One expected leaf-spine eBGP session."""

    plane: FabricPlane
    leaf: BgpRouter
    spine: BgpRouter


class EndpointPrefix(ExpectedStateModel):
    """Addressing and attachment metadata for one endpoint fabric NIC."""

    node: str
    interface: str
    plane: FabricPlane
    vrf: str
    address: IPv4Address
    prefix: IPv4Network
    gateway: IPv4Address
    attached_leaf: str


class ReachabilityExpectation(ExpectedStateModel):
    """One directed, same-plane endpoint reachability probe."""

    plane: FabricPlane
    source_node: str
    source_interface: str
    source_vrf: str
    source_address: IPv4Address
    destination_node: str
    destination_address: IPv4Address


class RouterPrefixExpectation(ExpectedStateModel):
    """One prefix expected in a router's RIB."""

    router: str
    plane: FabricPlane
    prefix: IPv4Network
    protocol: Literal["bgp", "connected"]
    min_next_hops: int = Field(ge=0)
    endpoint_node: str
    attached_leaf: str


class IsolationExpectation(ExpectedStateModel):
    """Cross-plane reachability and route isolation metadata."""

    source_plane: FabricPlane
    source_vrf: str
    destination_plane: FabricPlane
    source_nodes: tuple[str, ...]
    blocked_endpoint_addresses: tuple[IPv4Address, ...]
    forbidden_route_pools: tuple[IPv4Network, ...]


class ExpectedState(ExpectedStateModel):
    """Complete runtime contract emitted by the compiler."""

    schema_version: Literal[1] = 1
    fabric: str
    site: str
    source_revision: str
    bgp_adjacencies: tuple[BgpAdjacency, ...]
    endpoint_prefixes: tuple[EndpointPrefix, ...]
    router_prefixes: tuple[RouterPrefixExpectation, ...]
    reachability: tuple[ReachabilityExpectation, ...]
    isolation: tuple[IsolationExpectation, ...]


type InterfaceIndex = dict[tuple[str, str], Interface]


def _indexes(fabric: Fabric) -> tuple[dict[str, Node], InterfaceIndex]:
    nodes = {node.name: node for node in fabric.nodes}
    interfaces = {
        (node.name, interface.name): interface
        for node in fabric.nodes
        for interface in node.interfaces
    }
    return nodes, interfaces


def _interface_address(interfaces: InterfaceIndex, endpoint: LinkEndpoint) -> IPv4Interface:
    interface = interfaces.get((endpoint.node, endpoint.interface))
    if interface is None:
        raise ValueError(f"unknown link endpoint: {endpoint.node}:{endpoint.interface}")
    if len(interface.addresses) != 1:
        raise ValueError(
            f"expected one address on linked interface: {endpoint.node}:{endpoint.interface}"
        )
    return interface.addresses[0]


def _link_sides(
    link: Link,
    nodes: dict[str, Node],
    left_role: NodeRole,
    right_role: NodeRole,
) -> tuple[LinkEndpoint, LinkEndpoint] | None:
    endpoint_a_node = nodes.get(link.endpoint_a.node)
    endpoint_b_node = nodes.get(link.endpoint_b.node)
    if endpoint_a_node is None or endpoint_b_node is None:
        missing = link.endpoint_a.node if endpoint_a_node is None else link.endpoint_b.node
        raise ValueError(f"unknown link node: {missing}")
    if endpoint_a_node.role is left_role and endpoint_b_node.role is right_role:
        return (link.endpoint_a, link.endpoint_b)
    if endpoint_a_node.role is right_role and endpoint_b_node.role is left_role:
        return (link.endpoint_b, link.endpoint_a)
    return None


def _bgp_adjacencies(
    fabric: Fabric, nodes: dict[str, Node], interfaces: InterfaceIndex
) -> tuple[BgpAdjacency, ...]:
    adjacencies: list[BgpAdjacency] = []
    for link in fabric.links:
        if link.kind is not LinkKind.FABRIC:
            continue
        sides = _link_sides(link, nodes, NodeRole.LEAF, NodeRole.SPINE)
        if sides is None:
            raise ValueError("fabric links must connect one leaf and one spine")
        leaf_endpoint, spine_endpoint = sides
        leaf = nodes[leaf_endpoint.node]
        spine = nodes[spine_endpoint.node]
        if leaf.asn is None or spine.asn is None:
            raise ValueError("BGP routers must have ASNs")
        adjacencies.append(
            BgpAdjacency(
                plane=link.plane,
                leaf=BgpRouter(
                    node=leaf.name,
                    address=_interface_address(interfaces, leaf_endpoint).ip,
                    asn=leaf.asn,
                ),
                spine=BgpRouter(
                    node=spine.name,
                    address=_interface_address(interfaces, spine_endpoint).ip,
                    asn=spine.asn,
                ),
            )
        )
    return tuple(
        sorted(
            adjacencies,
            key=lambda item: (item.plane.value, item.leaf.node, item.spine.node),
        )
    )


def _endpoint_prefixes(
    fabric: Fabric, nodes: dict[str, Node], interfaces: InterfaceIndex
) -> tuple[EndpointPrefix, ...]:
    endpoints: list[EndpointPrefix] = []
    for link in fabric.links:
        if link.kind is not LinkKind.HOST:
            continue
        sides = _link_sides(link, nodes, NodeRole.COMPUTE, NodeRole.LEAF)
        if sides is None:
            raise ValueError("host links must connect one compute endpoint and one leaf")
        compute_endpoint, leaf_endpoint = sides
        compute_address = _interface_address(interfaces, compute_endpoint)
        leaf_address = _interface_address(interfaces, leaf_endpoint)
        if compute_address.network != leaf_address.network:
            raise ValueError("host link endpoints must share one prefix")
        endpoints.append(
            EndpointPrefix(
                node=compute_endpoint.node,
                interface=compute_endpoint.interface,
                plane=link.plane,
                vrf=f"fabric-{link.plane.value}",
                address=compute_address.ip,
                prefix=compute_address.network,
                gateway=leaf_address.ip,
                attached_leaf=leaf_endpoint.node,
            )
        )
    return tuple(sorted(endpoints, key=lambda item: (item.plane.value, item.node, item.interface)))


def _router_prefixes(
    nodes: dict[str, Node],
    endpoints: tuple[EndpointPrefix, ...],
    profile: PolicyProfile,
) -> tuple[RouterPrefixExpectation, ...]:
    expectations: list[RouterPrefixExpectation] = []
    routers = sorted(
        (
            node
            for node in nodes.values()
            if node.role in {NodeRole.LEAF, NodeRole.SPINE}
            and node.plane in profile.required_planes
        ),
        key=lambda item: item.name,
    )
    for router in routers:
        for endpoint in endpoints:
            if endpoint.plane is not router.plane:
                continue
            attached = router.role is NodeRole.LEAF and endpoint.attached_leaf == router.name
            protocol: Literal["bgp", "connected"] = "connected" if attached else "bgp"
            min_next_hops = 0
            if protocol == "bgp":
                min_next_hops = (
                    profile.spine_count_by_plane[router.plane]
                    if router.role is NodeRole.LEAF
                    else 1
                )
            expectations.append(
                RouterPrefixExpectation(
                    router=router.name,
                    plane=router.plane,
                    prefix=endpoint.prefix,
                    protocol=protocol,
                    min_next_hops=min_next_hops,
                    endpoint_node=endpoint.node,
                    attached_leaf=endpoint.attached_leaf,
                )
            )
    return tuple(
        sorted(
            expectations,
            key=lambda item: (item.plane.value, item.router, str(item.prefix)),
        )
    )


def _reachability(
    endpoints: tuple[EndpointPrefix, ...], profile: PolicyProfile
) -> tuple[ReachabilityExpectation, ...]:
    expectations: list[ReachabilityExpectation] = []
    for plane in sorted(profile.required_planes, key=lambda item: item.value):
        plane_endpoints = tuple(endpoint for endpoint in endpoints if endpoint.plane is plane)
        for source in plane_endpoints:
            for destination in plane_endpoints:
                if source.node == destination.node:
                    continue
                expectations.append(
                    ReachabilityExpectation(
                        plane=plane,
                        source_node=source.node,
                        source_interface=source.interface,
                        source_vrf=source.vrf,
                        source_address=source.address,
                        destination_node=destination.node,
                        destination_address=destination.address,
                    )
                )
    return tuple(
        sorted(
            expectations,
            key=lambda item: (
                item.plane.value,
                item.source_node,
                item.destination_node,
            ),
        )
    )


def _isolation(
    endpoints: tuple[EndpointPrefix, ...], profile: PolicyProfile
) -> tuple[IsolationExpectation, ...]:
    expectations: list[IsolationExpectation] = []
    planes = sorted(profile.required_planes, key=lambda item: item.value)
    for source_plane in planes:
        for destination_plane in planes:
            if source_plane is destination_plane:
                continue
            expectations.append(
                IsolationExpectation(
                    source_plane=source_plane,
                    source_vrf=f"fabric-{source_plane.value}",
                    destination_plane=destination_plane,
                    source_nodes=tuple(
                        sorted(
                            endpoint.node
                            for endpoint in endpoints
                            if endpoint.plane is source_plane
                        )
                    ),
                    blocked_endpoint_addresses=tuple(
                        sorted(
                            (
                                endpoint.address
                                for endpoint in endpoints
                                if endpoint.plane is destination_plane
                            ),
                            key=int,
                        )
                    ),
                    forbidden_route_pools=tuple(
                        sorted(
                            profile.plane_address_pools[destination_plane],
                            key=lambda network: (int(network.network_address), network.prefixlen),
                        )
                    ),
                )
            )
    return tuple(
        sorted(
            expectations,
            key=lambda item: (item.source_plane.value, item.destination_plane.value),
        )
    )


def generate_expected_state(fabric: Fabric, profile: PolicyProfile) -> ExpectedState:
    """Generate the deterministic M4 runtime contract for a validated fabric."""
    nodes, interfaces = _indexes(fabric)
    endpoints = _endpoint_prefixes(fabric, nodes, interfaces)
    return ExpectedState(
        fabric=fabric.name,
        site=fabric.site,
        source_revision=fabric.source_revision,
        bgp_adjacencies=_bgp_adjacencies(fabric, nodes, interfaces),
        endpoint_prefixes=endpoints,
        router_prefixes=_router_prefixes(nodes, endpoints, profile),
        reachability=_reachability(endpoints, profile),
        isolation=_isolation(endpoints, profile),
    )


def render_expected_state(state: ExpectedState) -> str:
    """Serialize expected state with stable indentation and a final newline."""
    return state.model_dump_json(indent=2) + "\n"
