"""Read-only NetBox snapshot and domain normalization adapter."""

import hashlib
import json
from ipaddress import IPv4Interface
from pathlib import Path
from typing import cast

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node
from aftwin.errors import NetBoxOperationError
from aftwin.netbox.client import NetBoxClient

JsonObject = dict[str, object]


def _object(value: object | None) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def _list(value: object | None) -> list[object]:
    return cast(list[object], value) if isinstance(value, list) else []


def _text(value: object | None, field: str | None = None) -> str:
    if field is not None:
        value = _object(value).get(field)
    if not isinstance(value, str):
        raise NetBoxOperationError("normalize", f"expected string field {field or '<value>'}")
    return value


def _integer(value: object | None, field: str | None = None) -> int:
    if field is not None:
        value = _object(value).get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise NetBoxOperationError("normalize", f"expected integer field {field or '<value>'}")
    return value


def _relation_id(value: object | None) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return _integer(value, "id")


def _choice(value: object | None) -> str:
    if isinstance(value, dict):
        choice = cast(JsonObject, value)
        return _text(choice.get("value"))
    return _text(value)


class NetBoxAdapter:
    """Fetch one site and normalize it without exposing pynetbox records."""

    def __init__(self, client: NetBoxClient) -> None:
        self.client = client

    def fetch_site(self, site_slug: str) -> JsonObject:
        """Fetch the raw objects needed to reconstruct one site."""
        site = self.client.one("dcim.sites", slug=site_slug)
        if site is None:
            raise NetBoxOperationError("fetch site", f"site '{site_slug}' was not found")
        site_id = _integer(site.get("id"))
        devices = self.client.list("dcim.devices", site_id=site_id)
        interfaces: list[JsonObject] = []
        for device in devices:
            for interface in self.client.list(
                "dcim.interfaces", device_id=_integer(device.get("id"))
            ):
                interface["_addresses"] = self.client.list(
                    "ipam.ip_addresses", interface_id=_integer(interface.get("id"))
                )
                interfaces.append(interface)
        return {
            "site": site,
            "devices": devices,
            "interfaces": interfaces,
            "cables": self.client.list("dcim.cables", site_id=site_id),
            "asns": self.client.list("ipam.asns"),
            "device_roles": self.client.list("dcim.device_roles"),
            "platforms": self.client.list("dcim.platforms"),
        }

    def save_snapshot(self, snapshot: JsonObject, path: Path) -> str:
        """Write stable JSON and return its SHA-256 revision."""
        content = json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def normalize(snapshot: JsonObject) -> Fabric:
        """Convert a raw site snapshot into the domain model."""
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        revision = hashlib.sha256(canonical.encode()).hexdigest()
        site = _object(snapshot.get("site"))
        device_records = [_object(item) for item in _list(snapshot.get("devices"))]
        interface_records = [_object(item) for item in _list(snapshot.get("interfaces"))]
        asn_by_id = {
            _integer(record.get("id")): _integer(record.get("asn"))
            for record in (_object(item) for item in _list(snapshot.get("asns")))
        }
        role_by_id = {
            _integer(record.get("id")): _text(record.get("slug"))
            for record in (_object(item) for item in _list(snapshot.get("device_roles")))
        }
        platform_by_id = {
            _integer(record.get("id")): _text(record.get("slug"))
            for record in (_object(item) for item in _list(snapshot.get("platforms")))
        }
        interfaces_by_device: dict[int, list[Interface]] = {}
        interface_endpoint_by_id: dict[int, LinkEndpoint] = {}

        device_name_by_id = {
            _integer(device.get("id")): _text(device.get("name")) for device in device_records
        }
        for record in interface_records:
            device_id = _relation_id(record.get("device"))
            name = _text(record.get("name"))
            custom = _object(record.get("custom_fields"))
            addresses = tuple(
                IPv4Interface(_text(_object(address).get("address")))
                for address in _list(record.get("_addresses"))
            )
            interface = Interface(
                name=name,
                role=InterfaceRole(_choice(custom.get("fabric_role"))),
                plane=FabricPlane(_choice(custom.get("fabric_plane"))),
                addresses=tuple(sorted(addresses, key=str)),
            )
            interfaces_by_device.setdefault(device_id, []).append(interface)
            interface_endpoint_by_id[_integer(record.get("id"))] = LinkEndpoint(
                node=device_name_by_id[device_id], interface=name
            )

        nodes: list[Node] = []
        for record in device_records:
            device_id = _integer(record.get("id"))
            custom = _object(record.get("custom_fields"))
            asn_value = custom.get("bgp_asn")
            asn_id = _relation_id(asn_value) if asn_value is not None else None
            role_value = record.get("role")
            platform_value = record.get("platform")
            role = (
                role_by_id[_relation_id(role_value)]
                if isinstance(role_value, int)
                else _text(role_value, "slug")
            )
            platform = (
                platform_by_id[_relation_id(platform_value)]
                if isinstance(platform_value, int)
                else _text(platform_value, "slug")
            )
            interfaces = tuple(
                sorted(interfaces_by_device.get(device_id, []), key=lambda item: item.name)
            )
            loopback = next(
                (
                    address
                    for interface in interfaces
                    if interface.role is InterfaceRole.LOOPBACK
                    for address in interface.addresses
                ),
                None,
            )
            nodes.append(
                Node(
                    name=_text(record.get("name")),
                    role=NodeRole(role),
                    platform=platform,
                    plane=FabricPlane(_choice(custom.get("fabric_plane"))),
                    asn=asn_by_id.get(asn_id) if asn_id is not None else None,
                    loopback=loopback,
                    interfaces=interfaces,
                )
            )

        links: list[Link] = []
        for cable in (_object(item) for item in _list(snapshot.get("cables"))):
            a_term = _object(_list(cable.get("a_terminations"))[0])
            b_term = _object(_list(cable.get("b_terminations"))[0])
            a_id = _integer(a_term.get("object_id") or a_term.get("id"))
            b_id = _integer(b_term.get("object_id") or b_term.get("id"))
            a = interface_endpoint_by_id[a_id]
            b = interface_endpoint_by_id[b_id]
            a_interface = next(
                interface
                for node in nodes
                if node.name == a.node
                for interface in node.interfaces
                if interface.name == a.interface
            )
            endpoint_nodes = [node for node in nodes if node.name in {a.node, b.node}]
            kind = (
                LinkKind.HOST
                if any(node.role in {NodeRole.COMPUTE, NodeRole.STORAGE} for node in endpoint_nodes)
                else LinkKind.FABRIC
            )
            links.append(
                Link(
                    endpoint_a=a,
                    endpoint_b=b,
                    plane=a_interface.plane,
                    kind=kind,
                )
            )
        return Fabric(
            name=_text(site.get("slug")),
            site=_text(site.get("slug")),
            nodes=tuple(sorted(nodes, key=lambda item: item.name)),
            links=tuple(
                sorted(
                    links,
                    key=lambda item: (
                        item.endpoint_a.node,
                        item.endpoint_a.interface,
                        item.endpoint_b.node,
                        item.endpoint_b.interface,
                    ),
                )
            ),
            source_revision=revision,
        )
