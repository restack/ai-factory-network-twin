"""Typed, NetBox-independent fabric models."""

from ipaddress import IPv4Interface

from pydantic import BaseModel, ConfigDict, Field

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole


class DomainModel(BaseModel):
    """Strict immutable base for normalized intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Interface(DomainModel):
    """A normalized node interface."""

    name: str
    role: InterfaceRole
    plane: FabricPlane
    addresses: tuple[IPv4Interface, ...] = ()


class Node(DomainModel):
    """A normalized network or endpoint node."""

    name: str
    role: NodeRole
    platform: str
    plane: FabricPlane
    asn: int | None = Field(default=None, ge=1, le=4_294_967_295)
    loopback: IPv4Interface | None = None
    interfaces: tuple[Interface, ...] = ()


class LinkEndpoint(DomainModel):
    """A stable interface reference."""

    node: str
    interface: str


class Link(DomainModel):
    """A normalized connection between two interfaces."""

    endpoint_a: LinkEndpoint
    endpoint_b: LinkEndpoint
    plane: FabricPlane
    kind: LinkKind


class Fabric(DomainModel):
    """Complete normalized fabric intent for one site."""

    name: str
    site: str
    nodes: tuple[Node, ...]
    links: tuple[Link, ...]
    source_revision: str
