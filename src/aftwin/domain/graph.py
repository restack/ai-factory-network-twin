"""Deterministic graph view of normalized fabric intent."""

from collections import defaultdict
from collections.abc import Iterable

import networkx as nx

from aftwin.domain.enums import FabricPlane, LinkKind, NodeRole
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node

type EndpointKey = tuple[str, str]


def _endpoint_key(endpoint: LinkEndpoint) -> EndpointKey:
    return (endpoint.node, endpoint.interface)


def _canonical_endpoints(link: Link) -> tuple[LinkEndpoint, LinkEndpoint]:
    if _endpoint_key(link.endpoint_a) <= _endpoint_key(link.endpoint_b):
        return (link.endpoint_a, link.endpoint_b)
    return (link.endpoint_b, link.endpoint_a)


def _link_sort_key(link: Link) -> tuple[str, str, str, str, str, str]:
    endpoint_u, endpoint_v = _canonical_endpoints(link)
    return (
        endpoint_u.node,
        endpoint_u.interface,
        endpoint_v.node,
        endpoint_v.interface,
        link.plane.value,
        link.kind.value,
    )


class FabricGraph:
    """Indexed NetworkX representation used by static policy rules.

    Node names and canonical link identifiers are stable regardless of the order
    in which normalized nodes, links, or link endpoints were supplied.
    """

    def __init__(self, fabric: Fabric) -> None:
        self.fabric = fabric
        self.graph: nx.MultiGraph[str] = nx.MultiGraph()
        self._nodes: dict[str, Node] = {}
        self._interfaces: dict[EndpointKey, Interface] = {}
        self._links: dict[str, Link] = {}
        self._links_by_node: dict[str, list[Link]] = defaultdict(list)
        self._links_by_interface: dict[EndpointKey, list[Link]] = defaultdict(list)
        self._build()

    def _build(self) -> None:
        for node in sorted(self.fabric.nodes, key=lambda candidate: candidate.name):
            if node.name in self._nodes:
                raise ValueError(f"duplicate node name: {node.name}")
            self._nodes[node.name] = node
            for interface in sorted(node.interfaces, key=lambda candidate: candidate.name):
                endpoint = (node.name, interface.name)
                if endpoint in self._interfaces:
                    raise ValueError(f"duplicate interface name: {node.name}:{interface.name}")
                self._interfaces[endpoint] = interface
            self.graph.add_node(
                node.name,
                role=node.role.value,
                plane=node.plane.value,
                platform=node.platform,
                asn=node.asn,
                loopback=str(node.loopback) if node.loopback is not None else None,
                tags=tuple(sorted(node.tags)),
            )

        occurrences: dict[tuple[str, str, str, str, str, str], int] = defaultdict(int)
        for link in sorted(self.fabric.links, key=_link_sort_key):
            endpoint_u, endpoint_v = _canonical_endpoints(link)
            sort_key = _link_sort_key(link)
            occurrences[sort_key] += 1
            link_id = (
                f"{endpoint_u.node}:{endpoint_u.interface}--"
                f"{endpoint_v.node}:{endpoint_v.interface}#{occurrences[sort_key]}"
            )
            self._links[link_id] = link

            for endpoint in (link.endpoint_a, link.endpoint_b):
                self._links_by_node[endpoint.node].append(link)
                self._links_by_interface[_endpoint_key(endpoint)].append(link)

            # Do not let NetworkX manufacture phantom nodes for invalid intent.
            # Reference validation policies can still inspect the original link.
            if endpoint_u.node not in self._nodes or endpoint_v.node not in self._nodes:
                continue
            self.graph.add_edge(
                endpoint_u.node,
                endpoint_v.node,
                key=link_id,
                link_id=link_id,
                kind=link.kind.value,
                plane=link.plane.value,
                interface_u=endpoint_u.interface,
                interface_v=endpoint_v.interface,
            )

    def node(self, name: str) -> Node | None:
        """Resolve a normalized node by name."""
        return self._nodes.get(name)

    def interface(self, node: str, interface: str) -> Interface | None:
        """Resolve a normalized interface by its stable endpoint reference."""
        return self._interfaces.get((node, interface))

    def link(self, link_id: str) -> Link | None:
        """Resolve a normalized link by its canonical graph edge identifier."""
        return self._links.get(link_id)

    def links_for_node(self, name: str) -> tuple[Link, ...]:
        """Return incident links in deterministic order."""
        return tuple(sorted(self._links_by_node.get(name, ()), key=_link_sort_key))

    def links_for_interface(self, node: str, interface: str) -> tuple[Link, ...]:
        """Return links terminating on an interface in deterministic order."""
        return tuple(
            sorted(self._links_by_interface.get((node, interface), ()), key=_link_sort_key)
        )

    def other_endpoint(self, link: Link, endpoint: LinkEndpoint) -> LinkEndpoint | None:
        """Resolve the endpoint opposite ``endpoint`` on ``link``."""
        if link.endpoint_a == endpoint:
            return link.endpoint_b
        if link.endpoint_b == endpoint:
            return link.endpoint_a
        return None

    def neighbor_endpoints(
        self,
        node: str,
        interface: str | None = None,
        *,
        kind: LinkKind | None = None,
        plane: FabricPlane | None = None,
    ) -> tuple[LinkEndpoint, ...]:
        """Return opposite endpoints connected to a node or one of its interfaces."""
        links: Iterable[Link]
        if interface is None:
            links = self.links_for_node(node)
        else:
            links = self.links_for_interface(node, interface)

        endpoint_filter = (node, interface)
        neighbors: list[LinkEndpoint] = []
        for link in links:
            if kind is not None and link.kind is not kind:
                continue
            if plane is not None and link.plane is not plane:
                continue
            if _endpoint_key(link.endpoint_a) == endpoint_filter:
                neighbors.append(link.endpoint_b)
            elif _endpoint_key(link.endpoint_b) == endpoint_filter:
                neighbors.append(link.endpoint_a)
            elif interface is None and link.endpoint_a.node == node:
                neighbors.append(link.endpoint_b)
            elif interface is None and link.endpoint_b.node == node:
                neighbors.append(link.endpoint_a)
        return tuple(sorted(neighbors, key=_endpoint_key))

    def neighbors(
        self,
        node: str,
        *,
        role: NodeRole | None = None,
        kind: LinkKind | None = None,
        plane: FabricPlane | None = None,
    ) -> tuple[Node, ...]:
        """Return unique neighboring nodes filtered by policy-relevant attributes."""
        resolved: dict[str, Node] = {}
        for endpoint in self.neighbor_endpoints(node, kind=kind, plane=plane):
            neighbor = self.node(endpoint.node)
            if neighbor is not None and (role is None or neighbor.role is role):
                resolved[neighbor.name] = neighbor
        return tuple(resolved[name] for name in sorted(resolved))
