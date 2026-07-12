"""Idempotently materialize development fixtures in NetBox."""

import re
from dataclasses import dataclass
from typing import Protocol

from aftwin.netbox.client import Record
from aftwin.netbox.fixture import NetBoxFixture

ROLE_COLORS = {
    "fabric-spine": "9c27b0",
    "fabric-leaf": "3f51b5",
    "compute": "4caf50",
    "storage": "ff9800",
}


class SeedClient(Protocol):
    """Writes required by the fixture seeder."""

    def ensure(
        self, path: str, lookup: dict[str, object], values: dict[str, object]
    ) -> tuple[Record, bool]: ...


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


@dataclass(slots=True)
class SeedResult:
    """Summary of idempotent writes."""

    created: int = 0
    existing: int = 0

    def record(self, was_created: bool) -> None:
        if was_created:
            self.created += 1
        else:
            self.existing += 1

    def as_dict(self) -> dict[str, int]:
        return {"created": self.created, "existing": self.existing}


class NetBoxSeeder:
    """Create a complete fixture using stable natural-key lookups."""

    def __init__(self, client: SeedClient) -> None:
        self.client = client
        self.result = SeedResult()

    def _ensure(self, path: str, lookup: dict[str, object], values: dict[str, object]) -> Record:
        record, created = self.client.ensure(path, lookup, values)
        self.result.record(created)
        return record

    def seed(self, fixture: NetBoxFixture) -> SeedResult:
        """Create all fixture objects in dependency order."""
        self.result = SeedResult()
        site = self._ensure(
            "dcim.sites",
            {"slug": fixture.site.slug},
            {"name": fixture.site.name, "slug": fixture.site.slug, "status": "active"},
        )
        tags = [
            self._ensure(
                "extras.tags",
                {"slug": _slug(tag)},
                {"name": tag, "slug": _slug(tag), "color": "607d8b"},
            )
            for tag in sorted(fixture.tags)
        ]
        tag_ids = [tag.id for tag in tags]

        plane_choices = self._ensure(
            "extras.custom_field_choice_sets",
            {"name": "aftwin-fabric-plane"},
            {
                "name": "aftwin-fabric-plane",
                "extra_choices": [["a", "Plane A"], ["b", "Plane B"], ["shared", "Shared"]],
            },
        )
        role_choices = self._ensure(
            "extras.custom_field_choice_sets",
            {"name": "aftwin-fabric-role"},
            {
                "name": "aftwin-fabric-role",
                "extra_choices": [
                    ["uplink", "Uplink"],
                    ["downlink", "Downlink"],
                    ["host", "Host"],
                    ["loopback", "Loopback"],
                    ["mgmt", "Management"],
                ],
            },
        )
        self._ensure(
            "extras.custom_fields",
            {"name": "fabric_plane"},
            {
                "name": "fabric_plane",
                "label": "Fabric plane",
                "type": "select",
                "object_types": ["dcim.device", "dcim.interface"],
                "choice_set": plane_choices.id,
            },
        )
        self._ensure(
            "extras.custom_fields",
            {"name": "fabric_role"},
            {
                "name": "fabric_role",
                "label": "Fabric role",
                "type": "select",
                "object_types": ["dcim.interface"],
                "choice_set": role_choices.id,
            },
        )
        self._ensure(
            "extras.custom_fields",
            {"name": "bgp_asn"},
            {
                "name": "bgp_asn",
                "label": "BGP ASN",
                "type": "object",
                "object_types": ["dcim.device"],
                "related_object_type": "ipam.asn",
            },
        )

        manufacturer = self._ensure(
            "dcim.manufacturers",
            {"slug": "aftwin"},
            {"name": "AI Factory Network Twin", "slug": "aftwin"},
        )
        rir = self._ensure(
            "ipam.rirs",
            {"slug": "private"},
            {"name": "Private", "slug": "private", "is_private": True},
        )

        roles: dict[str, Record] = {}
        platforms: dict[str, Record] = {}
        device_types: dict[str, Record] = {}
        for device in fixture.devices:
            role_name = device.role.value
            if role_name not in roles:
                roles[role_name] = self._ensure(
                    "dcim.device_roles",
                    {"slug": role_name},
                    {
                        "name": role_name,
                        "slug": role_name,
                        "color": ROLE_COLORS[role_name],
                    },
                )
            if device.platform not in platforms:
                platforms[device.platform] = self._ensure(
                    "dcim.platforms",
                    {"slug": device.platform},
                    {"name": device.platform, "slug": device.platform},
                )
                device_types[device.platform] = self._ensure(
                    "dcim.device_types",
                    {"slug": device.platform},
                    {
                        "manufacturer": manufacturer.id,
                        "model": device.platform,
                        "slug": device.platform,
                    },
                )

        devices: dict[str, Record] = {}
        interfaces: dict[tuple[str, str], Record] = {}
        for device in fixture.devices:
            custom_fields: dict[str, object] = {"fabric_plane": device.plane.value}
            if device.asn is not None:
                asn = self._ensure(
                    "ipam.asns",
                    {"asn": device.asn},
                    {"asn": device.asn, "rir": rir.id, "description": device.name},
                )
                custom_fields["bgp_asn"] = asn.id
            device_record = self._ensure(
                "dcim.devices",
                {"name": device.name, "site_id": site.id},
                {
                    "name": device.name,
                    "site": site.id,
                    "role": roles[device.role.value].id,
                    "device_type": device_types[device.platform].id,
                    "platform": platforms[device.platform].id,
                    "status": "active",
                    "tags": tag_ids,
                    "custom_fields": custom_fields,
                },
            )
            devices[device.name] = device_record
            for interface in device.interfaces:
                interface_record = self._ensure(
                    "dcim.interfaces",
                    {"device_id": device_record.id, "name": interface.name},
                    {
                        "device": device_record.id,
                        "name": interface.name,
                        "type": interface.type,
                        "enabled": True,
                        "custom_fields": {
                            "fabric_plane": interface.plane.value,
                            "fabric_role": interface.role.value,
                        },
                    },
                )
                interfaces[(device.name, interface.name)] = interface_record
                for address in interface.addresses:
                    address_text = str(address)
                    self._ensure(
                        "ipam.ip_addresses",
                        {"address": address_text},
                        {
                            "address": address_text,
                            "status": "active",
                            "assigned_object_type": "dcim.interface",
                            "assigned_object_id": interface_record.id,
                        },
                    )

        for link in fixture.links:
            a = interfaces[(link.a.device, link.a.interface)]
            b = interfaces[(link.b.device, link.b.interface)]
            endpoint_names = sorted(
                [
                    f"{link.a.device}:{link.a.interface}",
                    f"{link.b.device}:{link.b.interface}",
                ]
            )
            label = "--".join(endpoint_names)
            self._ensure(
                "dcim.cables",
                {"label": label},
                {
                    "label": label,
                    "status": "connected",
                    "a_terminations": [{"object_type": "dcim.interface", "object_id": a.id}],
                    "b_terminations": [{"object_type": "dcim.interface", "object_id": b.id}],
                },
            )
        return self.result
