"""Fabric-plane consistency and endpoint redundancy rules."""

from collections import defaultdict

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole
from aftwin.policy.findings import Finding, Severity
from aftwin.policy.rules.context import RuleContext, link_key

NETWORK_ROLES = {NodeRole.SPINE, NodeRole.LEAF}
ENDPOINT_ROLES = {NodeRole.COMPUTE, NodeRole.STORAGE}


def evaluate(context: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    leaf_by_compute_plane: dict[str, dict[FabricPlane, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for node in context.fabric.nodes:
        if node.role in NETWORK_ROLES and node.plane not in context.profile.required_planes:
            findings.append(
                Finding(
                    rule_id="PLN001",
                    severity=Severity.ERROR,
                    target=f"node:{node.name}",
                    message=(
                        f"Network node '{node.name}' must belong to one required fabric "
                        f"plane; found '{node.plane.value}'."
                    ),
                    hint="Set 'fabric_plane' to a plane required by the policy profile.",
                )
            )
        if node.role in ENDPOINT_ROLES:
            host_planes = {
                interface.plane
                for interface in node.interfaces
                if interface.role is InterfaceRole.HOST
            }
            for interface in node.interfaces:
                if (
                    interface.role is InterfaceRole.HOST
                    and interface.plane not in context.profile.required_planes
                ):
                    findings.append(
                        Finding(
                            rule_id="PLN002",
                            severity=Severity.ERROR,
                            target=f"interface:{node.name}/{interface.name}",
                            message=(
                                f"Compute fabric interface '{node.name}/{interface.name}' "
                                f"has invalid plane '{interface.plane.value}'."
                            ),
                            hint="Assign the interface to one plane required by the profile.",
                        )
                    )
            missing = context.profile.required_planes - host_planes
            if missing:
                plane_text = ", ".join(sorted(plane.value for plane in missing))
                findings.append(
                    Finding(
                        rule_id="PLN004",
                        severity=Severity.ERROR,
                        target=f"node:{node.name}",
                        message=(
                            f"Compute node '{node.name}' is missing fabric interfaces for "
                            f"planes: {plane_text}."
                        ),
                        hint="Add one host-facing interface in each missing plane.",
                    )
                )

    for link in context.fabric.links:
        if link.kind is LinkKind.MANAGEMENT:
            continue
        a = context.endpoint(link.endpoint_a)
        b = context.endpoint(link.endpoint_b)
        if a is None or b is None:
            continue
        endpoint_planes = (a[1].plane, b[1].plane)
        if link.plane not in context.profile.required_planes or any(
            plane is not link.plane for plane in endpoint_planes
        ):
            values = ",".join(plane.value for plane in endpoint_planes)
            findings.append(
                Finding(
                    rule_id="PLN003",
                    severity=Severity.ERROR,
                    target=f"link:{link_key(link)}",
                    message=(
                        f"Link '{link_key(link)}' has inconsistent planes: "
                        f"link={link.plane.value}, endpoints={values}."
                    ),
                    hint="Align the cable endpoints and link with one required fabric plane.",
                )
            )
        if link.kind is LinkKind.HOST:
            endpoints = ((a[0], b[0]), (b[0], a[0]))
            for endpoint, peer in endpoints:
                if endpoint.role in ENDPOINT_ROLES and peer.role is NodeRole.LEAF:
                    leaf_by_compute_plane[endpoint.name][link.plane].add(peer.name)

    for node, by_plane in sorted(leaf_by_compute_plane.items()):
        leaves = [leaf for plane in context.profile.required_planes for leaf in by_plane[plane]]
        duplicates = sorted({leaf for leaf in leaves if leaves.count(leaf) > 1})
        for leaf in duplicates:
            findings.append(
                Finding(
                    rule_id="PLN005",
                    severity=Severity.ERROR,
                    target=f"node:{node}",
                    message=f"Compute node '{node}' uses leaf '{leaf}' for multiple fabric planes.",
                    hint="Connect each plane to an independent leaf device.",
                )
            )
    return findings
