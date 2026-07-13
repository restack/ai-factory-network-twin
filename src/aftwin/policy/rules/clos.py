"""Clos topology and link-role rules."""

from aftwin.domain.enums import ENDPOINT_ROLES, NETWORK_ROLES, InterfaceRole, LinkKind, NodeRole
from aftwin.policy.findings import Finding, Severity
from aftwin.policy.rules.context import RuleContext, link_key


def evaluate(context: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for plane in sorted(context.profile.required_planes, key=lambda item: item.value):
        spines = {
            node.name
            for node in context.fabric.nodes
            if node.role is NodeRole.SPINE and node.plane is plane
        }
        expected_count = context.profile.spine_count_by_plane[plane]
        if len(spines) != expected_count:
            findings.append(
                Finding(
                    rule_id="CLS001",
                    severity=Severity.ERROR,
                    target=f"plane:{plane.value}",
                    message=(
                        f"Plane '{plane.value}' has {len(spines)} spines; expected "
                        f"{expected_count}."
                    ),
                    hint="Restore the configured spine inventory.",
                )
            )
        for leaf in (
            node
            for node in context.fabric.nodes
            if node.role is NodeRole.LEAF and node.plane is plane
        ):
            fabric_uplinks = [
                link
                for link in context.graph.links_for_node(leaf.name)
                if link.kind is LinkKind.FABRIC
                and link.plane is plane
                and any(
                    endpoint is not None and endpoint[0].role is NodeRole.SPINE
                    for endpoint in (
                        context.endpoint(link.endpoint_a),
                        context.endpoint(link.endpoint_b),
                    )
                )
            ]
            actual = {
                node.name
                for node in context.graph.neighbors(
                    leaf.name, role=NodeRole.SPINE, kind=LinkKind.FABRIC, plane=plane
                )
            }
            if (
                actual != spines
                or len(actual) != expected_count
                or len(fabric_uplinks) != expected_count
            ):
                findings.append(
                    Finding(
                        rule_id="CLS001",
                        severity=Severity.ERROR,
                        target=f"node:{leaf.name}",
                        message=(
                            f"Leaf '{leaf.name}' has spine neighbors {sorted(actual)}; "
                            f"expected {sorted(spines)}, with {len(fabric_uplinks)}/"
                            f"{expected_count} uplinks."
                        ),
                        hint="Add or repair the missing leaf-spine links.",
                    )
                )

    for link in context.fabric.links:
        a = context.endpoint(link.endpoint_a)
        b = context.endpoint(link.endpoint_b)
        if a is None or b is None:
            continue
        roles = {a[0].role, b[0].role}
        if link.kind is LinkKind.FABRIC and roles != {NodeRole.SPINE, NodeRole.LEAF}:
            findings.append(
                Finding(
                    rule_id="CLS002",
                    severity=Severity.ERROR,
                    target=f"link:{link_key(link)}",
                    message=(
                        f"Fabric link '{link_key(link)}' connects invalid roles: "
                        f"{sorted(role.value for role in roles)}."
                    ),
                    hint="Connect each fabric link between one spine and one leaf.",
                )
            )
        if link.kind is LinkKind.HOST:
            valid_roles = NodeRole.LEAF in roles and bool(roles & ENDPOINT_ROLES)
            valid_interfaces = a[1].role is InterfaceRole.HOST and b[1].role is InterfaceRole.HOST
            if not valid_roles or not valid_interfaces:
                findings.append(
                    Finding(
                        rule_id="CLS003",
                        severity=Severity.ERROR,
                        target=f"link:{link_key(link)}",
                        message=(
                            f"Host link '{link_key(link)}' has invalid endpoint roles or "
                            "interface roles."
                        ),
                        hint=(
                            "Connect one leaf host interface to one compute or storage "
                            "host interface."
                        ),
                    )
                )

    for node in context.fabric.nodes:
        for interface in node.interfaces:
            if interface.role is InterfaceRole.HOST:
                count = sum(
                    link.kind is LinkKind.HOST
                    for link in context.graph.links_for_interface(node.name, interface.name)
                )
                if count != 1:
                    findings.append(
                        Finding(
                            rule_id="CLS004",
                            severity=Severity.ERROR,
                            target=f"interface:{node.name}/{interface.name}",
                            message=(
                                f"Host interface '{node.name}/{interface.name}' terminates "
                                f"{count} host links; expected 1."
                            ),
                            hint="Attach the interface to exactly one valid host link.",
                        )
                    )
        if node.role in NETWORK_ROLES and not context.graph.neighbors(
            node.name, kind=LinkKind.FABRIC
        ):
            findings.append(
                Finding(
                    rule_id="CLS005",
                    severity=Severity.ERROR,
                    target=f"node:{node.name}",
                    message=f"Network node '{node.name}' is isolated from the fabric graph.",
                    hint="Add at least one valid leaf-spine fabric link.",
                )
            )
    return findings
