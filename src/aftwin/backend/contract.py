"""Renderer-facing platform backend contract.

A backend owns every platform-specific decision behind one renderer name:
generated configuration artifacts, the Containerlab node body, and the
source-name to runtime-name interface mapping. Backends never execute
subprocesses; runtime adapters consume their declarations.
"""

from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aftwin.backend.capabilities import BackendCapability
from aftwin.compiler.expected_state import ExpectedState
from aftwin.domain.models import Fabric, Node


class BackendRoleClass(StrEnum):
    """Which fabric role family a backend may render."""

    NETWORK = "network"
    ENDPOINT = "endpoint"


class GeneratedFile(BaseModel):
    """One deterministic artifact produced by a backend renderer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    content: str = Field(min_length=1)
    executable: bool = False

    @field_validator("path")
    @classmethod
    def require_relative_posix_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("generated path must be a normalized relative POSIX path")
        return value


class PlatformBackend(ABC):
    """Capability-declared renderer contract for one runtime platform."""

    name: ClassVar[str]
    role_class: ClassVar[BackendRoleClass]
    capabilities: ClassVar[frozenset[BackendCapability]]

    def runtime_interface_name(self, source_name: str) -> str:
        """Map one NetBox source interface name to its runtime name."""
        return source_name

    @abstractmethod
    def render_node(
        self, fabric: Fabric, node: Node, expected: ExpectedState
    ) -> tuple[GeneratedFile, ...]:
        """Render one node's deterministic configuration artifacts."""

    @abstractmethod
    def containerlab_node(self, node: Node, *, kind: str, image: str, group: str) -> dict[str, Any]:
        """Render one node's Containerlab topology body."""
