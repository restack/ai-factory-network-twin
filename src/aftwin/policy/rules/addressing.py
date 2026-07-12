"""Loopback, point-to-point, and plane-pool addressing rules."""

from aftwin.domain.enums import InterfaceRole, LinkKind, NodeRole
from aftwin.domain.models import Interface, Link
from aftwin.policy.findings import Finding, Severity
from aftwin.policy.rules.context import RuleContext, link_key

NETWORK_ROLES = {NodeRole.SPINE, NodeRole.LEAF}


def _valid_p2p(a: Interface, b: Interface, prefix_length: int) -> bool:
    if len(a.addresses) != 1 or len(b.addresses) != 1:
        return False
    address_a = a.addresses[0]
    address_b = b.addresses[0]
    return (
        address_a.network.prefixlen == prefix_length
        and address_b.network.prefixlen == prefix_length
        and address_a.network == address_b.network
        and address_a.ip != address_b.ip
    )


def _p2p_finding(link: Link, *, fabric: bool) -> Finding:
    label = "Fabric" if fabric else "Host"
    rule_id = "ADR002" if fabric else "ADR003"
    return Finding(
        rule_id=rule_id,
        severity=Severity.ERROR,
        target=f"link:{link_key(link)}",
        message=(
            f"{label} link '{link_key(link)}' does not use one shared point-to-point network."
        ),
        hint="Assign the two usable addresses from one unique profile-sized subnet.",
    )


def evaluate(context: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for node in context.fabric.nodes:
        if node.role in NETWORK_ROLES:
            loopbacks = [
                address
                for interface in node.interfaces
                if interface.role is InterfaceRole.LOOPBACK
                for address in interface.addresses
            ]
            if len(loopbacks) != 1 or loopbacks[0].network.prefixlen != 32:
                values = ", ".join(sorted(str(address) for address in loopbacks)) or "none"
                findings.append(
                    Finding(
                        rule_id="ADR001",
                        severity=Severity.ERROR,
                        target=f"node:{node.name}",
                        message=(
                            f"Network node '{node.name}' must have exactly one IPv4 /32 "
                            f"loopback; found {values}."
                        ),
                        hint="Configure one unique IPv4 /32 on the loopback interface.",
                    )
                )
        for interface in node.interfaces:
            if interface.role is InterfaceRole.MGMT:
                continue
            pools = context.profile.plane_address_pools.get(interface.plane, ())
            for address in interface.addresses:
                if pools and not any(address.ip in pool for pool in pools):
                    findings.append(
                        Finding(
                            rule_id="ADR006",
                            severity=Severity.ERROR,
                            target=f"address:{address.ip}",
                            message=(
                                f"Address '{address}' is outside configured pools for plane "
                                f"'{interface.plane.value}'."
                            ),
                            hint="Allocate the interface address from its plane policy pool.",
                        )
                    )

    for link in context.fabric.links:
        if link.kind not in {LinkKind.FABRIC, LinkKind.HOST}:
            continue
        a = context.endpoint(link.endpoint_a)
        b = context.endpoint(link.endpoint_b)
        if a is None or b is None:
            continue
        prefix_length = (
            context.profile.fabric_p2p_prefix_length
            if link.kind is LinkKind.FABRIC
            else context.profile.host_p2p_prefix_length
        )
        if not _valid_p2p(a[1], b[1], prefix_length):
            findings.append(_p2p_finding(link, fabric=link.kind is LinkKind.FABRIC))

    planes = sorted(context.profile.required_planes, key=lambda item: item.value)
    for index, plane_a in enumerate(planes):
        for plane_b in planes[index + 1 :]:
            for pool_a in context.profile.plane_address_pools[plane_a]:
                for pool_b in context.profile.plane_address_pools[plane_b]:
                    if pool_a.overlaps(pool_b):
                        findings.append(
                            Finding(
                                rule_id="ADR005",
                                severity=Severity.ERROR,
                                target=f"fabric:{context.fabric.site}",
                                message=(
                                    f"Plane address pools overlap: plane {plane_a.value} "
                                    f"'{pool_a}' and plane {plane_b.value} '{pool_b}'."
                                ),
                                hint="Allocate non-overlapping address pools to the planes.",
                            )
                        )
    return findings
