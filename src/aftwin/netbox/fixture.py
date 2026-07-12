"""Versioned, declarative NetBox development fixtures."""

import hashlib
from ipaddress import IPv4Interface
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole
from aftwin.domain.models import Fabric, Interface, Link, LinkEndpoint, Node


class FixtureModel(BaseModel):
    """Strict base model for fixture input."""

    model_config = ConfigDict(extra="forbid")


class SiteFixture(FixtureModel):
    name: str
    slug: str


class InterfaceFixture(FixtureModel):
    name: str
    role: InterfaceRole
    plane: FabricPlane
    addresses: tuple[IPv4Interface, ...] = ()
    type: str = "other"


class DeviceFixture(FixtureModel):
    name: str
    role: NodeRole
    platform: str
    plane: FabricPlane
    asn: int | None = Field(default=None, ge=1, le=4_294_967_295)
    interfaces: tuple[InterfaceFixture, ...]


class EndpointFixture(FixtureModel):
    device: str
    interface: str


class LinkFixture(FixtureModel):
    a: EndpointFixture
    b: EndpointFixture
    plane: FabricPlane
    kind: LinkKind


class NetBoxFixture(FixtureModel):
    """All intended NetBox objects for a reproducible lab fixture."""

    schema_version: int = Field(ge=1, le=1)
    name: str
    site: SiteFixture
    tags: tuple[str, ...]
    devices: tuple[DeviceFixture, ...]
    links: tuple[LinkFixture, ...]

    @model_validator(mode="after")
    def validate_references(self) -> "NetBoxFixture":
        interfaces = {
            (device.name, interface.name)
            for device in self.devices
            for interface in device.interfaces
        }
        if len({device.name for device in self.devices}) != len(self.devices):
            raise ValueError("device names must be unique")
        for link in self.links:
            for endpoint in (link.a, link.b):
                if (endpoint.device, endpoint.interface) not in interfaces:
                    raise ValueError(
                        f"link references unknown interface {endpoint.device}:{endpoint.interface}"
                    )
        return self


def load_fixture(path: Path) -> NetBoxFixture:
    """Load and validate a fixture YAML document."""
    with path.open(encoding="utf-8") as stream:
        data: object = yaml.safe_load(stream)
    return NetBoxFixture.model_validate(data)


def fixture_to_fabric(fixture: NetBoxFixture) -> Fabric:
    """Convert a validated Git fixture to the same domain model as NetBox."""
    nodes: list[Node] = []
    for device in fixture.devices:
        interfaces = tuple(
            Interface(
                name=interface.name,
                role=interface.role,
                plane=interface.plane,
                addresses=interface.addresses,
            )
            for interface in sorted(device.interfaces, key=lambda item: item.name)
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
                name=device.name,
                role=device.role,
                platform=device.platform,
                plane=device.plane,
                asn=device.asn,
                loopback=loopback,
                tags=tuple(sorted(fixture.tags)),
                interfaces=interfaces,
            )
        )
    links = tuple(
        Link(
            endpoint_a=LinkEndpoint(node=link.a.device, interface=link.a.interface),
            endpoint_b=LinkEndpoint(node=link.b.device, interface=link.b.interface),
            plane=link.plane,
            kind=link.kind,
        )
        for link in sorted(
            fixture.links,
            key=lambda item: (
                item.a.device,
                item.a.interface,
                item.b.device,
                item.b.interface,
            ),
        )
    )
    revision = hashlib.sha256(
        (fixture.model_dump_json(exclude_none=False) + "\n").encode()
    ).hexdigest()
    return Fabric(
        name=fixture.name,
        site=fixture.site.slug,
        nodes=tuple(sorted(nodes, key=lambda item: item.name)),
        links=links,
        source_revision=revision,
    )
