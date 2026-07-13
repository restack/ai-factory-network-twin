from collections.abc import Callable
from ipaddress import IPv4Interface
from pathlib import Path

import pytest

from aftwin.domain.enums import FabricPlane, LinkKind
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node, SourceSelection
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.engine import PolicyEngine
from aftwin.policy.profile import PolicyProfile, load_policy_profile


def _load_case(name: str) -> tuple[Fabric, PolicyProfile]:
    fixture = load_fixture(Path(f"fixtures/{name}.yaml"))
    profile = load_policy_profile(Path(f"config/policies/{name}.yaml"))
    return fixture_to_fabric(fixture), profile


def _rule_ids(fabric: Fabric, profile: PolicyProfile) -> set[str]:
    return {finding.rule_id for finding in PolicyEngine().validate(fabric, profile).findings}


def _node(fabric: Fabric, name: str) -> Node:
    return next(node for node in fabric.nodes if node.name == name)


def _replace_node(fabric: Fabric, replacement: Node) -> Fabric:
    return fabric.model_copy(
        update={
            "nodes": tuple(
                replacement if node.name == replacement.name else node for node in fabric.nodes
            )
        }
    )


def _update_node(fabric: Fabric, name: str, **updates: object) -> Fabric:
    return _replace_node(fabric, _node(fabric, name).model_copy(update=updates))


def _update_interface(
    fabric: Fabric,
    node_name: str,
    interface_name: str,
    transform: Callable[[Interface], Interface],
) -> Fabric:
    node = _node(fabric, node_name)
    interfaces = tuple(
        transform(interface) if interface.name == interface_name else interface
        for interface in node.interfaces
    )
    return _replace_node(fabric, node.model_copy(update={"interfaces": interfaces}))


def _replace_link(fabric: Fabric, original: Link, replacement: Link) -> Fabric:
    replaced = False
    links: list[Link] = []
    for link in fabric.links:
        if not replaced and link is original:
            links.append(replacement)
            replaced = True
        else:
            links.append(link)
    assert replaced
    return fabric.model_copy(update={"links": tuple(links)})


def _link(fabric: Fabric, *endpoints: tuple[str, str]) -> Link:
    expected = set(endpoints)
    return next(
        link
        for link in fabric.links
        if {
            (link.endpoint_a.node, link.endpoint_a.interface),
            (link.endpoint_b.node, link.endpoint_b.interface),
        }
        == expected
    )


@pytest.mark.parametrize("name", ["smoke", "mini-dual-plane"])
def test_valid_fixture_passes_its_explicit_profile(name: str) -> None:
    fabric, profile = _load_case(name)

    report = PolicyEngine().validate(fabric, profile)

    assert report.passed
    assert report.findings == ()


def test_source_selection_reports_ignored_interfaces_and_boundary_cables() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = fabric.model_copy(
        update={
            "selection": SourceSelection(
                selected_device_count=12,
                included_interface_count=36,
                ignored_interface_count=3,
                included_cable_count=16,
                boundary_cable_ids=(91, 90),
            )
        }
    )

    report = PolicyEngine().validate(fabric, profile)

    assert report.passed
    assert {finding.rule_id for finding in report.findings} == {"SRC001", "SRC002"}
    assert report.warning_count == 1
    assert report.info_count == 1


def test_broken_cable_reports_stable_endpoint_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    original = fabric.links[0]
    broken = original.model_copy(
        update={
            "endpoint_b": LinkEndpoint(
                node=original.endpoint_b.node,
                interface="missing-interface",
            )
        }
    )
    fabric = _replace_link(fabric, original, broken)

    report = PolicyEngine().validate(fabric, profile)

    assert "GEN005" in {finding.rule_id for finding in report.findings}
    assert any(
        finding.rule_id == "GEN005" and finding.target.startswith("link:")
        for finding in report.findings
    )


def test_missing_leaf_spine_cable_reports_clos_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    missing = _link(fabric, ("spine-a1", "eth1"), ("leaf-a1", "eth1"))
    fabric = fabric.model_copy(
        update={"links": tuple(link for link in fabric.links if link is not missing)}
    )

    assert "CLS001" in _rule_ids(fabric, profile)


def test_extra_parallel_leaf_spine_uplink_reports_clos_degree_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    leaf = _node(fabric, "leaf-a1")
    spine = _node(fabric, "spine-a1")
    leaf_extra = Interface(
        name="eth99",
        role=leaf.interfaces[0].role,
        plane=FabricPlane.A,
        addresses=(IPv4Interface("10.0.2.1/31"),),
    )
    spine_extra = Interface(
        name="eth99",
        role=spine.interfaces[0].role,
        plane=FabricPlane.A,
        addresses=(IPv4Interface("10.0.2.0/31"),),
    )
    fabric = _replace_node(
        fabric, leaf.model_copy(update={"interfaces": (*leaf.interfaces, leaf_extra)})
    )
    fabric = _replace_node(
        fabric, spine.model_copy(update={"interfaces": (*spine.interfaces, spine_extra)})
    )
    fabric = fabric.model_copy(
        update={
            "links": (
                *fabric.links,
                Link(
                    endpoint_a=LinkEndpoint(node="leaf-a1", interface="eth99"),
                    endpoint_b=LinkEndpoint(node="spine-a1", interface="eth99"),
                    plane=FabricPlane.A,
                    kind=LinkKind.FABRIC,
                ),
            )
        }
    )

    assert "CLS001" in _rule_ids(fabric, profile)


def test_missing_and_duplicate_asns_report_stable_rules() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_node(fabric, "spine-a1", asn=None)
    fabric = _update_node(fabric, "spine-a2", asn=_node(fabric, "leaf-a1").asn)

    assert {"GEN003", "GEN007"} <= _rule_ids(fabric, profile)


def test_unsupported_platform_and_missing_loopback_report_general_rules() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_node(fabric, "spine-a1", platform="unsupported", loopback=None)

    assert {"GEN002", "GEN004"} <= _rule_ids(fabric, profile)


def test_invalid_compute_plane_reports_interface_and_link_rules() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_interface(
        fabric,
        "gpu01",
        "eth1",
        lambda interface: interface.model_copy(update={"plane": FabricPlane.SHARED}),
    )

    assert {"PLN002", "PLN003"} <= _rule_ids(fabric, profile)


def test_policy_engine_collects_multiple_independent_errors() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_node(fabric, "gpu01", tags=())
    fabric = _update_node(fabric, "spine-a1", asn=None)
    fabric = _update_interface(
        fabric,
        "gpu02",
        "eth1",
        lambda interface: interface.model_copy(update={"plane": FabricPlane.SHARED}),
    )
    invalid_loopback = IPv4Interface("10.255.1.1/31")
    fabric = _update_interface(
        fabric,
        "spine-b1",
        "lo",
        lambda interface: interface.model_copy(update={"addresses": (invalid_loopback,)}),
    )
    fabric = _update_node(fabric, "spine-b1", loopback=invalid_loopback)

    report = PolicyEngine().validate(fabric, profile)

    assert {"GEN001", "GEN003", "PLN002", "PLN003", "ADR001"} <= {
        finding.rule_id for finding in report.findings
    }
    assert report.error_count >= 5


def test_duplicate_ip_is_reported_once_by_address() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    duplicate = _node(fabric, "spine-a1").loopback
    assert duplicate is not None
    fabric = _update_interface(
        fabric,
        "spine-a2",
        "lo",
        lambda interface: interface.model_copy(update={"addresses": (duplicate,)}),
    )
    fabric = _update_node(fabric, "spine-a2", loopback=duplicate)

    findings = PolicyEngine().validate(fabric, profile).findings
    duplicates = [finding for finding in findings if finding.rule_id == "GEN006"]

    assert len(duplicates) == 1
    assert duplicates[0].target == f"address:{duplicate.ip}"


def test_interface_reuse_reports_general_cabling_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    reused = _link(fabric, ("spine-a1", "eth1"), ("leaf-a1", "eth1"))
    fabric = fabric.model_copy(update={"links": (*fabric.links, reused)})

    assert "GEN008" in _rule_ids(fabric, profile)


def test_invalid_fabric_endpoint_roles_report_clos_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    original = _link(fabric, ("leaf-a1", "eth3"), ("gpu01", "eth1"))
    invalid = original.model_copy(update={"kind": LinkKind.FABRIC})
    fabric = _replace_link(fabric, original, invalid)

    assert "CLS002" in _rule_ids(fabric, profile)


def test_invalid_fabric_point_to_point_network_reports_addressing_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_interface(
        fabric,
        "leaf-a1",
        "eth1",
        lambda interface: interface.model_copy(
            update={"addresses": (IPv4Interface("10.0.0.1/30"),)}
        ),
    )

    assert "ADR002" in _rule_ids(fabric, profile)


def test_missing_compute_plane_reports_redundancy_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    gpu = _node(fabric, "gpu01")
    fabric = _replace_node(
        fabric,
        gpu.model_copy(
            update={
                "interfaces": tuple(
                    interface
                    for interface in gpu.interfaces
                    if interface.plane is not FabricPlane.B
                )
            }
        ),
    )

    assert "PLN004" in _rule_ids(fabric, profile)


def test_network_node_outside_required_planes_reports_plane_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_node(fabric, "spine-a1", plane=FabricPlane.SHARED)

    assert "PLN001" in _rule_ids(fabric, profile)


def test_compute_reusing_leaf_across_planes_reports_redundancy_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    original = _link(fabric, ("leaf-b1", "eth3"), ("gpu01", "eth2"))
    replacement = original.model_copy(
        update={"endpoint_a": LinkEndpoint(node="leaf-a1", interface="eth3")}
    )
    fabric = _replace_link(fabric, original, replacement)

    assert "PLN005" in _rule_ids(fabric, profile)


def test_invalid_host_endpoint_roles_report_clos_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    original = _link(fabric, ("leaf-a1", "eth3"), ("gpu01", "eth1"))
    replacement = original.model_copy(
        update={
            "endpoint_a": LinkEndpoint(node="gpu01", interface="eth1"),
            "endpoint_b": LinkEndpoint(node="gpu02", interface="eth1"),
        }
    )
    fabric = _replace_link(fabric, original, replacement)

    assert "CLS003" in _rule_ids(fabric, profile)


def test_uncabled_host_interface_reports_host_degree_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    missing = _link(fabric, ("leaf-a1", "eth3"), ("gpu01", "eth1"))
    fabric = fabric.model_copy(
        update={"links": tuple(link for link in fabric.links if link is not missing)}
    )

    assert "CLS004" in _rule_ids(fabric, profile)


def test_spine_without_fabric_links_reports_isolation_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = fabric.model_copy(
        update={
            "links": tuple(
                link
                for link in fabric.links
                if link.endpoint_a.node != "spine-a1" and link.endpoint_b.node != "spine-a1"
            )
        }
    )

    assert "CLS005" in _rule_ids(fabric, profile)


def test_invalid_host_point_to_point_network_reports_addressing_rule() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    fabric = _update_interface(
        fabric,
        "gpu01",
        "eth1",
        lambda interface: interface.model_copy(
            update={"addresses": (IPv4Interface("10.0.1.1/30"),)}
        ),
    )

    assert "ADR003" in _rule_ids(fabric, profile)


def test_overlapping_pools_and_out_of_pool_address_report_address_rules() -> None:
    fabric, profile = _load_case("mini-dual-plane")
    overlapping = profile.model_copy(
        update={
            "plane_address_pools": {
                FabricPlane.A: profile.plane_address_pools[FabricPlane.A],
                FabricPlane.B: (
                    *profile.plane_address_pools[FabricPlane.B],
                    IPv4Interface("10.0.0.1/16").network,
                ),
            }
        }
    )
    fabric = _update_interface(
        fabric,
        "gpu01",
        "eth1",
        lambda interface: interface.model_copy(
            update={"addresses": (IPv4Interface("192.0.2.1/31"),)}
        ),
    )

    assert {"ADR005", "ADR006"} <= _rule_ids(fabric, overlapping)
