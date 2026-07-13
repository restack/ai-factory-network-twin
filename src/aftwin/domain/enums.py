"""Shared domain enumerations."""

from enum import StrEnum


class NodeRole(StrEnum):
    """Roles supported by the initial fabric profile."""

    SPINE = "fabric-spine"
    LEAF = "fabric-leaf"
    COMPUTE = "compute"
    STORAGE = "storage"


class FabricPlane(StrEnum):
    """Fabric failure-domain membership."""

    A = "a"
    B = "b"
    SHARED = "shared"


class InterfaceRole(StrEnum):
    """Meaning of an interface within the fabric."""

    UPLINK = "uplink"
    DOWNLINK = "downlink"
    HOST = "host"
    LOOPBACK = "loopback"
    MGMT = "mgmt"


class LinkKind(StrEnum):
    """Supported link classes."""

    FABRIC = "fabric"
    HOST = "host"
    MANAGEMENT = "management"


NETWORK_ROLES = frozenset({NodeRole.SPINE, NodeRole.LEAF})
ENDPOINT_ROLES = frozenset({NodeRole.COMPUTE, NodeRole.STORAGE})
