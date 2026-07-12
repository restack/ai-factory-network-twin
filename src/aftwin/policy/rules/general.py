"""General source and uniqueness rules."""

from collections import defaultdict

from aftwin.domain.enums import NodeRole
from aftwin.policy.findings import Finding, Severity
from aftwin.policy.rules.context import RuleContext, endpoint_key, link_key

NETWORK_ROLES = {NodeRole.SPINE, NodeRole.LEAF}


def evaluate(context: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    addresses: dict[str, list[str]] = defaultdict(list)
    asns: dict[int, list[str]] = defaultdict(list)

    for node in context.fabric.nodes:
        if context.profile.required_tag not in node.tags:
            findings.append(
                Finding(
                    rule_id="GEN001",
                    severity=Severity.ERROR,
                    target=f"node:{node.name}",
                    message=(
                        f"Device '{node.name}' is missing required tag "
                        f"'{context.profile.required_tag}'."
                    ),
                    hint=(
                        f"Add the '{context.profile.required_tag}' tag to device "
                        f"'{node.name}' in NetBox."
                    ),
                )
            )
        if node.role in NETWORK_ROLES:
            if node.platform not in context.profile.supported_network_platforms:
                supported = ", ".join(sorted(context.profile.supported_network_platforms))
                findings.append(
                    Finding(
                        rule_id="GEN002",
                        severity=Severity.ERROR,
                        target=f"node:{node.name}",
                        message=(
                            f"Network node '{node.name}' uses unsupported platform "
                            f"'{node.platform}'."
                        ),
                        hint=f"Assign one of the supported platforms: {supported}.",
                    )
                )
            if node.asn is None:
                findings.append(
                    Finding(
                        rule_id="GEN003",
                        severity=Severity.ERROR,
                        target=f"node:{node.name}",
                        message=f"Network node '{node.name}' has no BGP ASN.",
                        hint=("Assign a native NetBox ASN through the device 'bgp_asn' field."),
                    )
                )
            else:
                asns[node.asn].append(node.name)
            if node.loopback is None:
                findings.append(
                    Finding(
                        rule_id="GEN004",
                        severity=Severity.ERROR,
                        target=f"node:{node.name}",
                        message=f"Network node '{node.name}' has no loopback address.",
                        hint="Add one loopback interface with one IPv4 /32 address.",
                    )
                )
        for interface in node.interfaces:
            owner = f"{node.name}/{interface.name}"
            for address in interface.addresses:
                addresses[str(address.ip)].append(owner)
            links = context.graph.links_for_interface(node.name, interface.name)
            if len(links) > 1:
                link_names = ", ".join(sorted(link_key(link) for link in links))
                findings.append(
                    Finding(
                        rule_id="GEN008",
                        severity=Severity.ERROR,
                        target=f"interface:{owner}",
                        message=f"Interface '{owner}' terminates multiple links: {link_names}.",
                        hint="Keep exactly one cable on the interface.",
                    )
                )

    for link in context.fabric.links:
        for endpoint in (link.endpoint_a, link.endpoint_b):
            if context.endpoint(endpoint) is None:
                findings.append(
                    Finding(
                        rule_id="GEN005",
                        severity=Severity.ERROR,
                        target=f"link:{link_key(link)}",
                        message=(
                            f"Link '{link_key(link)}' references unknown interface "
                            f"'{endpoint_key(endpoint)}'."
                        ),
                        hint="Repair or remove the cable endpoint in NetBox.",
                    )
                )

    for address, owners in sorted(addresses.items()):
        if len(owners) > 1:
            owner_text = ", ".join(sorted(owners))
            findings.append(
                Finding(
                    rule_id="GEN006",
                    severity=Severity.ERROR,
                    target=f"address:{address}",
                    message=(
                        f"IP address '{address}' is assigned to multiple interfaces: {owner_text}."
                    ),
                    hint="Assign a unique address to each interface.",
                )
            )
    for asn, nodes in sorted(asns.items()):
        if len(nodes) > 1:
            node_text = ", ".join(sorted(nodes))
            findings.append(
                Finding(
                    rule_id="GEN007",
                    severity=Severity.ERROR,
                    target=f"asn:{asn}",
                    message=f"ASN '{asn}' is assigned to multiple network nodes: {node_text}.",
                    hint="Assign a unique ASN to each spine and leaf.",
                )
            )
    return findings
