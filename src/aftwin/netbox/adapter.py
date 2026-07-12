"""Read-only NetBox snapshot and domain normalization adapter."""

import hashlib
import json
from ipaddress import IPv4Interface
from pathlib import Path
from typing import Protocol, cast

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node
from aftwin.errors import NetBoxOperationError

JsonObject = dict[str, object]


class ReadClient(Protocol):
    """Read operations required by the adapter."""

    def one(self, path: str, **filters: object) -> JsonObject | None: ...

    def list(self, path: str, **filters: object) -> list[JsonObject]: ...


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


def _select_ids(records: list[JsonObject], ids: set[int]) -> list[JsonObject]:
    return [record for record in records if _integer(record.get("id")) in ids]


def _serialize_snapshot(snapshot: JsonObject) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _snapshot_revision(snapshot: JsonObject) -> str:
    return hashlib.sha256(_serialize_snapshot(snapshot).encode()).hexdigest()


def _single_termination(cable: JsonObject, side: str) -> JsonObject:
    terminations = _list(cable.get(f"{side}_terminations"))
    if len(terminations) != 1:
        raise NetBoxOperationError(
            "normalize", f"cable {_integer(cable.get('id'))} must have one {side} termination"
        )
    return _object(terminations[0])


class NetBoxAdapter:
    """Fetch one site and normalize it without exposing pynetbox records."""

    def __init__(self, client: ReadClient) -> None:
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
        role_ids = {_relation_id(device.get("role")) for device in devices}
        platform_ids = {_relation_id(device.get("platform")) for device in devices}
        tag_ids = {_relation_id(tag) for device in devices for tag in _list(device.get("tags"))}
        asn_ids = {
            _relation_id(asn)
            for device in devices
            if (asn := _object(device.get("custom_fields")).get("bgp_asn")) is not None
        }
        return {
            "site": site,
            "devices": devices,
            "interfaces": interfaces,
            "cables": self.client.list("dcim.cables", site_id=site_id),
            "asns": _select_ids(self.client.list("ipam.asns"), asn_ids),
            "device_roles": _select_ids(self.client.list("dcim.device_roles"), role_ids),
            "platforms": _select_ids(self.client.list("dcim.platforms"), platform_ids),
            "tags": _select_ids(self.client.list("extras.tags"), tag_ids),
        }

    @staticmethod
    def save_snapshot(snapshot: JsonObject, path: Path) -> str:
        """Write stable JSON and return its SHA-256 revision."""
        content = _serialize_snapshot(snapshot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        return _snapshot_revision(snapshot)

    @staticmethod
    def normalize(snapshot: JsonObject) -> Fabric:
        """Convert a raw site snapshot into the domain model."""
        revision = _snapshot_revision(snapshot)
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
        tag_by_id = {
            _integer(record.get("id")): _text(record.get("slug"))
            for record in (_object(item) for item in _list(snapshot.get("tags")))
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
            tags = tuple(
                sorted(
                    tag_by_id[_relation_id(tag)] if isinstance(tag, int) else _text(tag, "slug")
                    for tag in _list(record.get("tags"))
                )
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
                    tags=tags,
                    interfaces=interfaces,
                )
            )

        links: list[Link] = []
        for cable in (_object(item) for item in _list(snapshot.get("cables"))):
            a_term = _single_termination(cable, "a")
            b_term = _single_termination(cable, "b")
            a_id = _integer(a_term.get("object_id") or a_term.get("id"))
            b_id = _integer(b_term.get("object_id") or b_term.get("id"))
            try:
                a = interface_endpoint_by_id[a_id]
                b = interface_endpoint_by_id[b_id]
            except KeyError as error:
                raise NetBoxOperationError(
                    "normalize",
                    f"cable {_integer(cable.get('id'))} references an unknown interface",
                ) from error
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
