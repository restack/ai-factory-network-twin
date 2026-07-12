"""Shared immutable policy evaluation context."""

from dataclasses import dataclass

from aftwin.domain.graph import FabricGraph
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node
from aftwin.policy.profile import PolicyProfile


@dataclass(frozen=True, slots=True)
class RuleContext:
    fabric: Fabric
    graph: FabricGraph
    profile: PolicyProfile

    def endpoint(self, endpoint: LinkEndpoint) -> tuple[Node, Interface] | None:
        node = self.graph.node(endpoint.node)
        interface = self.graph.interface(endpoint.node, endpoint.interface)
        if node is None or interface is None:
            return None
        return node, interface


def endpoint_key(endpoint: LinkEndpoint) -> str:
    return f"{endpoint.node}/{endpoint.interface}"


def link_key(link: Link) -> str:
    return "--".join(sorted((endpoint_key(link.endpoint_a), endpoint_key(link.endpoint_b))))
