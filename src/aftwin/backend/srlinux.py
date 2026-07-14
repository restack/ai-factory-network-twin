"""Nokia SR Linux platform backend."""

import json
from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network
from typing import Any, ClassVar, cast

from aftwin.backend.capabilities import BackendCapability
from aftwin.backend.contract import (
    BackendRoleClass,
    GeneratedFile,
    NetworkObservedStateCollector,
    PlatformBackend,
)
from aftwin.compiler.expected_state import ExpectedState
from aftwin.domain.models import Fabric, Node
from aftwin.render.srlinux import (
    render_srlinux_config,
    srlinux_containerlab_interface_name,
)
from aftwin.verify.bgp import ObservedBgpNeighbor, ObservedBgpRouter
from aftwin.verify.routes import ObservedRoute, ObservedRouteTable

# SR Linux route-table owners translated to the vendor-neutral protocol names
# used by expected state. Unlisted owners pass through unchanged.
_PROTOCOL_NAMES = {"local": "connected"}


def _plain(value: object) -> object:
    """Strip YANG module prefixes from mapping keys and identity values."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return {key.rsplit(":", 1)[-1]: _plain(item) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_plain(item) for item in cast(list[object], value)]
    return value


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be a JSON object")
    return cast(Mapping[str, Any], value)


def _records(value: object, context: str) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a JSON array")
    return [_mapping(item, context) for item in cast(list[object], value)]


def _identity(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} must be a non-empty string")
    return value.rsplit(":", 1)[-1]


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{context} must be an integer")
    try:
        return int(value)
    except ValueError as error:
        raise ValueError(f"{context} must be an integer") from error


def _default_network_instance(payload: object, router: str) -> Mapping[str, Any]:
    root = _mapping(_plain(payload), f"SR Linux state for {router}")
    instances = _records(root.get("network-instance"), f"network instances for {router}")
    for instance in instances:
        if instance.get("name") == "default":
            return instance
    raise ValueError(f"SR Linux state for {router} has no default network instance")


class SrLinuxObservedStateCollector(NetworkObservedStateCollector):
    """Collect SR Linux evidence through sr_cli state queries as JSON."""

    def readiness_command(self) -> tuple[str, ...]:
        return ("sr_cli", "info", "from", "state", "system", "information", "version")

    def bgp_summary_command(self) -> tuple[str, ...]:
        return (
            "sr_cli",
            "info from state network-instance default protocols bgp | as json",
        )

    def parse_bgp_summary(self, router: str, payload: str | Mapping[str, Any]) -> ObservedBgpRouter:
        raw: object = json.loads(payload) if isinstance(payload, str) else payload
        instance = _default_network_instance(raw, router)
        bgp = _mapping(
            _mapping(instance.get("protocols"), f"protocols for {router}").get("bgp"),
            f"BGP state for {router}",
        )
        local_asn = _integer(bgp.get("autonomous-system"), f"local ASN for {router}")
        neighbors: list[ObservedBgpNeighbor] = []
        for record in _records(bgp.get("neighbor", []), f"BGP neighbors for {router}"):
            address = record.get("peer-address")
            if not isinstance(address, str) or not address:
                raise ValueError(f"BGP neighbor for {router} has no peer address")
            neighbors.append(
                ObservedBgpNeighbor(
                    address=address,
                    remote_asn=_integer(
                        record.get("peer-as"), f"remote ASN for {router}:{address}"
                    ),
                    state=_identity(record.get("session-state"), f"state for {router}:{address}"),
                )
            )
        return ObservedBgpRouter(
            router=router,
            local_asn=local_asn,
            neighbors=tuple(sorted(neighbors, key=lambda item: item.address)),
        )

    def route_table_command(self) -> tuple[str, ...]:
        return (
            "sr_cli",
            "info from state network-instance default route-table | as json",
        )

    def parse_route_table(
        self, router: str, payload: str | Mapping[str, Any]
    ) -> ObservedRouteTable:
        raw: object = json.loads(payload) if isinstance(payload, str) else payload
        instance = _default_network_instance(raw, router)
        table = _mapping(instance.get("route-table"), f"route table for {router}")

        next_hop_addresses: dict[int, IPv4Address] = {}
        for record in _records(table.get("next-hop", []), f"next hops for {router}"):
            address = record.get("ip-address")
            if isinstance(address, str) and address:
                next_hop_addresses[_integer(record.get("index"), "next hop index")] = IPv4Address(
                    address
                )
        group_members: dict[int, tuple[int, ...]] = {}
        for record in _records(table.get("next-hop-group", []), f"next hop groups for {router}"):
            members = tuple(
                _integer(member.get("next-hop"), "next hop reference")
                for member in _records(record.get("next-hop", []), "next hop group members")
                if member.get("next-hop") is not None
            )
            group_members[_integer(record.get("index"), "next hop group index")] = members

        ipv4 = _mapping(table.get("ipv4-unicast", {}), f"IPv4 route table for {router}")
        routes: list[ObservedRoute] = []
        for record in _records(ipv4.get("route", []), f"routes for {router}"):
            if record.get("active") is False:
                continue
            prefix = record.get("ipv4-prefix")
            if not isinstance(prefix, str) or not prefix:
                raise ValueError(f"route for {router} has no prefix")
            protocol = _identity(record.get("route-type"), f"protocol for {router}:{prefix}")
            hops: set[IPv4Address] = set()
            group = record.get("next-hop-group")
            if group is not None:
                for member in group_members.get(_integer(group, "next hop group"), ()):
                    address = next_hop_addresses.get(member)
                    if address is not None:
                        hops.add(address)
            routes.append(
                ObservedRoute(
                    prefix=IPv4Network(prefix),
                    protocol=_PROTOCOL_NAMES.get(protocol, protocol).casefold(),
                    next_hops=tuple(sorted(hops, key=int)),
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


class SrLinuxBackend(PlatformBackend):
    """Render SR Linux routers as native Containerlab NOS nodes."""

    name: ClassVar[str] = "srlinux"
    role_class: ClassVar[BackendRoleClass] = BackendRoleClass.NETWORK
    capabilities: ClassVar[frozenset[BackendCapability]] = frozenset(
        {
            BackendCapability.BGP_IPV4_UNICAST,
            BackendCapability.ECMP_MULTIPATH,
            BackendCapability.BGP_OBSERVED_STATE,
            BackendCapability.ROUTE_OBSERVED_STATE,
        }
    )

    def runtime_interface_name(self, source_name: str) -> str:
        return srlinux_containerlab_interface_name(source_name)

    def render_node(
        self, fabric: Fabric, node: Node, expected: ExpectedState
    ) -> tuple[GeneratedFile, ...]:
        return (
            GeneratedFile(
                path=f"configs/routers/{node.name}/srlinux.cli",
                content=render_srlinux_config(fabric, node),
            ),
        )

    def containerlab_node(
        self, node: Node, *, kind: str, image: str, group: str, node_type: str | None = None
    ) -> dict[str, Any]:
        definition: dict[str, Any] = {"kind": kind, "image": image}
        if node_type is not None:
            definition["type"] = node_type
        definition["group"] = group
        definition["startup-config"] = f"configs/routers/{node.name}/srlinux.cli"
        return definition

    @property
    def collector(self) -> NetworkObservedStateCollector:
        return _COLLECTOR


_COLLECTOR = SrLinuxObservedStateCollector()
