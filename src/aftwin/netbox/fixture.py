"""Versioned, declarative NetBox development fixtures."""

from ipaddress import IPv4Interface
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole


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
