from ipaddress import IPv4Interface

from aftwin.domain.enums import (
    FabricPlane,
    InterfaceRole,
    LinkKind,
    NodeRole,
)
from aftwin.domain.graph import FabricGraph
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node


def _node(
    name: str,
    role: NodeRole,
    interface: str,
    interface_role: InterfaceRole,
    address: str,
) -> Node:
    return Node(
        name=name,
        role=role,
        platform="frr" if role is not NodeRole.COMPUTE else "linux-endpoint",
        plane=FabricPlane.A if role is not NodeRole.COMPUTE else FabricPlane.SHARED,
        asn=None if role is NodeRole.COMPUTE else 65_000 + len(name),
        interfaces=(
            Interface(
                name=interface,
                role=interface_role,
                plane=FabricPlane.A,
                addresses=(IPv4Interface(address),),
            ),
        ),
    )


def _fabric(*, reversed_order: bool = False) -> Fabric:
    spine = _node("spine-a1", NodeRole.SPINE, "eth1", InterfaceRole.DOWNLINK, "10.0.0.0/31")
    leaf = Node(
        name="leaf-a1",
        role=NodeRole.LEAF,
        platform="frr",
        plane=FabricPlane.A,
        asn=65_101,
        tags=("z-tag", "a-tag"),
        interfaces=(
            Interface(
                name="eth2",
                role=InterfaceRole.HOST,
                plane=FabricPlane.A,
                addresses=(IPv4Interface("10.0.1.0/31"),),
            ),
            Interface(
                name="eth1",
                role=InterfaceRole.UPLINK,
                plane=FabricPlane.A,
                addresses=(IPv4Interface("10.0.0.1/31"),),
            ),
        ),
    )
    compute = _node("gpu01", NodeRole.COMPUTE, "eth1", InterfaceRole.HOST, "10.0.1.1/31")
    fabric_link = Link(
        endpoint_a=LinkEndpoint(node="leaf-a1", interface="eth1"),
        endpoint_b=LinkEndpoint(node="spine-a1", interface="eth1"),
        plane=FabricPlane.A,
        kind=LinkKind.FABRIC,
    )
    host_link = Link(
        endpoint_a=LinkEndpoint(node="gpu01", interface="eth1"),
        endpoint_b=LinkEndpoint(node="leaf-a1", interface="eth2"),
        plane=FabricPlane.A,
        kind=LinkKind.HOST,
    )
    nodes = (spine, leaf, compute)
    links = (fabric_link, host_link)
    if reversed_order:
        nodes = tuple(reversed(nodes))
        links = tuple(
            link.model_copy(
                update={
                    "endpoint_a": link.endpoint_b,
                    "endpoint_b": link.endpoint_a,
                }
            )
            for link in reversed(links)
        )
    return Fabric(
        name="small",
        site="lab",
        nodes=nodes,
        links=links,
        source_revision="test",
    )


def _shape(graph: FabricGraph) -> tuple[object, object]:
    nodes = tuple(
        (
            name,
            tuple(sorted((key, str(value)) for key, value in attributes.items())),
        )
        for name, attributes in graph.graph.nodes(data=True)
    )
    edges = tuple(
        (
            node_a,
            node_b,
            key,
            tuple(sorted((attribute, str(value)) for attribute, value in attributes.items())),
        )
        for node_a, node_b, key, attributes in graph.graph.edges(keys=True, data=True)
    )
    return nodes, edges


def test_graph_shape_and_attributes_are_deterministic() -> None:
    graph = FabricGraph(_fabric())
    reordered_graph = FabricGraph(_fabric(reversed_order=True))

    assert tuple(graph.graph.nodes) == ("gpu01", "leaf-a1", "spine-a1")
    assert graph.graph.number_of_nodes() == 3
    assert graph.graph.number_of_edges() == 2
    assert _shape(graph) == _shape(reordered_graph)
    assert graph.graph.nodes["leaf-a1"] == {
        "role": "fabric-leaf",
        "plane": "a",
        "platform": "frr",
        "asn": 65_101,
        "loopback": None,
        "tags": ("a-tag", "z-tag"),
    }
    assert tuple(key for _, _, key in graph.graph.edges(keys=True)) == (
        "gpu01:eth1--leaf-a1:eth2#1",
        "leaf-a1:eth1--spine-a1:eth1#1",
    )


def test_graph_resolves_nodes_interfaces_links_and_neighbors() -> None:
    graph = FabricGraph(_fabric())
    leaf_interface = graph.interface("leaf-a1", "eth1")

    assert graph.node("missing") is None
    assert graph.interface("leaf-a1", "missing") is None
    assert leaf_interface is not None
    assert leaf_interface.role is InterfaceRole.UPLINK
    assert len(graph.links_for_node("leaf-a1")) == 2
    assert len(graph.links_for_interface("leaf-a1", "eth1")) == 1
    assert graph.links_for_interface("missing", "eth1") == ()
    assert graph.link("missing") is None
    assert (
        graph.link("leaf-a1:eth1--spine-a1:eth1#1")
        == graph.links_for_interface("leaf-a1", "eth1")[0]
    )
    assert tuple(node.name for node in graph.neighbors("leaf-a1")) == (
        "gpu01",
        "spine-a1",
    )
    assert tuple(
        node.name for node in graph.neighbors("leaf-a1", role=NodeRole.SPINE, kind=LinkKind.FABRIC)
    ) == ("spine-a1",)
    assert graph.neighbor_endpoints("leaf-a1", "eth1") == (
        LinkEndpoint(node="spine-a1", interface="eth1"),
    )


def test_other_endpoint_rejects_an_endpoint_not_on_the_link() -> None:
    graph = FabricGraph(_fabric())
    link = graph.links_for_interface("leaf-a1", "eth1")[0]

    assert graph.other_endpoint(link, link.endpoint_a) == link.endpoint_b
    assert graph.other_endpoint(link, LinkEndpoint(node="leaf-a1", interface="missing")) is None
