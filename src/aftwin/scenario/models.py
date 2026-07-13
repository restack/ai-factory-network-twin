"""Strict Git-owned failure-scenario definitions."""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aftwin.domain.enums import FabricPlane
from aftwin.domain.types import SafeIdentifier


class ScenarioType(StrEnum):
    """Failure actions supported by the MVP scenario runner."""

    LINK_DOWN = "link-down"
    SPINE_DOWN = "spine-down"


class ScenarioModel(BaseModel):
    """Immutable base that rejects undeclared scenario configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class FailureTarget(ScenarioModel):
    """Runtime node and optional interfaces affected by a failure action."""

    node: SafeIdentifier
    interfaces: tuple[SafeIdentifier, ...] = ()

    @field_validator("interfaces")
    @classmethod
    def canonicalize_interfaces(cls, interfaces: tuple[str, ...]) -> tuple[str, ...]:
        """Reject duplicate targets and make action ordering stable."""
        if any(not interface for interface in interfaces):
            raise ValueError("target interfaces cannot be empty")
        if len(set(interfaces)) != len(interfaces):
            raise ValueError("target interfaces must be unique")
        return tuple(sorted(interfaces))


class FailureAction(ScenarioModel):
    """One reversible failure and its exact runtime target."""

    type: ScenarioType
    target: FailureTarget

    @model_validator(mode="after")
    def validate_target_shape(self) -> "FailureAction":
        """Keep each scenario limited to one well-defined failure."""
        if self.type is ScenarioType.LINK_DOWN and len(self.target.interfaces) != 1:
            raise ValueError("link-down requires exactly one target interface")
        if self.type is ScenarioType.SPINE_DOWN and self.target.interfaces:
            raise ValueError("spine-down targets a node and cannot list interfaces")
        return self


class ExpectedProbe(ScenarioModel):
    """One directed endpoint reachability check that must survive the failure."""

    plane: FabricPlane
    source_node: SafeIdentifier
    destination_node: SafeIdentifier

    @model_validator(mode="after")
    def require_distinct_endpoints(self) -> "ExpectedProbe":
        if self.plane is FabricPlane.SHARED:
            raise ValueError("scenario probes must select plane a or b")
        if self.source_node == self.destination_node:
            raise ValueError("scenario probe endpoints must be distinct")
        return self


def _probe_key(probe: ExpectedProbe) -> tuple[str, str, str]:
    return (probe.plane.value, probe.source_node, probe.destination_node)


class ScenarioExpectations(ScenarioModel):
    """Connectivity that must remain available while the failure is active."""

    surviving_planes: tuple[FabricPlane, ...]
    probes: tuple[ExpectedProbe, ...]

    @field_validator("surviving_planes")
    @classmethod
    def canonicalize_planes(cls, planes: tuple[FabricPlane, ...]) -> tuple[FabricPlane, ...]:
        if not planes:
            raise ValueError("at least one surviving plane is required")
        if FabricPlane.SHARED in planes:
            raise ValueError("surviving planes must be plane a or b")
        if len(set(planes)) != len(planes):
            raise ValueError("surviving planes must be unique")
        return tuple(sorted(planes, key=lambda plane: plane.value))

    @field_validator("probes")
    @classmethod
    def canonicalize_probes(cls, probes: tuple[ExpectedProbe, ...]) -> tuple[ExpectedProbe, ...]:
        if not probes:
            raise ValueError("at least one surviving reachability probe is required")
        keys = [_probe_key(probe) for probe in probes]
        if len(set(keys)) != len(keys):
            raise ValueError("scenario probes must be unique")
        return tuple(sorted(probes, key=_probe_key))

    @model_validator(mode="after")
    def require_probe_for_each_surviving_plane(self) -> "ScenarioExpectations":
        probe_planes = {probe.plane for probe in self.probes}
        surviving = set(self.surviving_planes)
        if probe_planes != surviving:
            raise ValueError("probes must cover exactly the surviving planes")
        return self


class FailureScenario(ScenarioModel):
    """Versioned and deterministic scenario loaded from Git-owned YAML."""

    schema_version: Literal[1] = 1
    name: SafeIdentifier
    description: str = Field(min_length=1)
    failure: FailureAction
    expected: ScenarioExpectations

    @property
    def revision(self) -> str:
        """Return a deterministic content identity for report provenance."""
        content = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_scenario(path: Path) -> FailureScenario:
    """Load and validate one strict failure scenario from YAML."""
    with path.open(encoding="utf-8") as stream:
        data: object = yaml.safe_load(stream)
    return FailureScenario.model_validate(data)
