"""Git-owned policy profile configuration."""

from ipaddress import IPv4Network
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aftwin.domain.enums import FabricPlane


class PolicyProfile(BaseModel):
    """Explicit topology and addressing requirements for one fabric profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    required_planes: frozenset[FabricPlane]
    supported_network_platforms: frozenset[str]
    required_tag: str = "ai-fabric"
    fabric_p2p_prefix_length: int = Field(default=31, ge=0, le=32)
    host_p2p_prefix_length: int = Field(default=31, ge=0, le=32)
    spine_count_by_plane: dict[FabricPlane, int]
    plane_address_pools: dict[FabricPlane, tuple[IPv4Network, ...]]

    @field_validator("required_planes")
    @classmethod
    def require_fabric_plane(cls, planes: frozenset[FabricPlane]) -> frozenset[FabricPlane]:
        if not planes or FabricPlane.SHARED in planes:
            raise ValueError("required_planes must contain plane a, plane b, or both")
        return planes

    @field_validator("spine_count_by_plane")
    @classmethod
    def require_positive_spine_counts(
        cls, counts: dict[FabricPlane, int]
    ) -> dict[FabricPlane, int]:
        if any(plane is FabricPlane.SHARED or count < 1 for plane, count in counts.items()):
            raise ValueError("spine counts must be positive and assigned to plane a or b")
        return counts

    @model_validator(mode="after")
    def require_plane_configuration(self) -> "PolicyProfile":
        if set(self.spine_count_by_plane) != set(self.required_planes):
            raise ValueError("spine_count_by_plane must match required_planes")
        if set(self.plane_address_pools) != set(self.required_planes):
            raise ValueError("plane_address_pools must match required_planes")
        return self


def load_policy_profile(path: Path) -> PolicyProfile:
    """Load a strict policy profile from YAML."""
    with path.open(encoding="utf-8") as stream:
        data: object = yaml.safe_load(stream)
    return PolicyProfile.model_validate(data)
