"""Guarded deployment lifecycle for compiled local labs."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from aftwin.compiler.manifest import BuildManifest, sha256_file
from aftwin.errors import AftwinError, ExitCode
from aftwin.runtime.executor import (
    CommandExecutionError,
    CommandFailureKind,
    CommandResult,
)

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]

DEPLOYMENT_STAMP_PATH = Path("runtime/deployment.json")


class DeploymentStamp(BaseModel):
    """Content-derived identity of the build currently deployed at runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    lab_name: str = Field(min_length=1)
    topology_file: Literal["topology.clab.yml"] = "topology.clab.yml"
    topology_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    build_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(min_length=1)
    container_names: tuple[str, ...]

    @field_validator("container_names")
    @classmethod
    def sort_and_require_unique_names(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        ordered = tuple(sorted(names))
        if not ordered or len(set(ordered)) != len(ordered):
            raise ValueError("deployment container names must be non-empty and unique")
        if any(not name for name in ordered):
            raise ValueError("deployment container names must be non-empty and unique")
        return ordered

    @classmethod
    def from_build(cls, site_dir: Path, manifest: BuildManifest) -> Self:
        """Derive runtime identity from an integrity-checked build."""
        topology = site_dir / "topology.clab.yml"
        return cls(
            lab_name=LabLifecycle.topology_name(topology),
            topology_sha256=sha256_file(topology),
            build_hash=manifest.build_hash,
            source_revision=manifest.source_revision,
            container_names=tuple(LabLifecycle.expected_container_names(topology)),
        )

    def to_json(self) -> str:
        """Render canonical newline-terminated JSON without volatile timestamps."""
        return json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"

    def write(self, site_dir: Path) -> Path:
        """Atomically publish this stamp below the build's runtime directory."""
        destination = site_dir / DEPLOYMENT_STAMP_PATH
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        try:
            temporary.write_text(self.to_json(), encoding="utf-8", newline="\n")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination


class ContainerlabRuntime(Protocol):
    """Lifecycle operations required from the Containerlab command adapter."""

    def deploy(self, topology: Path, *, reconfigure: bool = False) -> CommandResult: ...

    def destroy(self, topology: Path, *, cleanup: bool = True) -> CommandResult: ...

    def inspect(self, topology: Path) -> CommandResult: ...

    def inspect_all(self) -> CommandResult: ...

    def exec(self, topology: Path, node: str, command: Sequence[str]) -> CommandResult: ...


class LabLifecycleError(AftwinError):
    """A safe, structured failure while managing an ephemeral lab."""

    def __init__(
        self, reason: str, *, operation: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            code="lab_lifecycle_failed",
            message=f"Lab {operation} failed: {reason}",
            exit_code=ExitCode.DEPLOYMENT,
            details={"operation": operation, **(details or {})},
        )


@dataclass(frozen=True, slots=True)
class LabInspection:
    """Parsed Containerlab inspection evidence."""

    payload: JsonValue
    command: CommandResult | None

    @property
    def nodes(self) -> tuple[dict[str, JsonValue], ...]:
        """Flatten Containerlab's lab-name keyed node records."""
        if isinstance(self.payload, list):
            return tuple(item for item in self.payload if isinstance(item, dict))
        if not isinstance(self.payload, dict):
            return ()
        records: list[dict[str, JsonValue]] = []
        for value in self.payload.values():
            if not isinstance(value, list):
                continue
            records.extend(item for item in value if isinstance(item, dict))
        return tuple(records)

    @property
    def running(self) -> bool:
        """Whether Containerlab reported any resource for this topology."""
        return bool(self.nodes)

    @property
    def all_running(self) -> bool:
        """Whether every reported node is explicitly in the running state."""
        return bool(self.nodes) and all(node.get("state") == "running" for node in self.nodes)


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    """Outcome of a guarded deploy or destroy operation."""

    operation: str
    changed: bool
    command: CommandResult | None
    inspection: LabInspection


class LabLifecycle:
    """Enforce artifact, validation, collision, and cleanup lifecycle gates."""

    def __init__(self, containerlab: ContainerlabRuntime) -> None:
        self._containerlab = containerlab

    @staticmethod
    def topology_path(site_dir: Path) -> Path:
        """Return the canonical generated topology path for a site build."""
        return site_dir / "topology.clab.yml"

    def inspect(self, site_dir: Path) -> LabInspection:
        """Return parsed state for a compiled topology."""
        topology = self.topology_path(site_dir)
        self._require_file(topology, operation="inspection")
        try:
            result = self._containerlab.inspect_all()
        except CommandExecutionError as error:
            if self._is_no_running_labs(error):
                return LabInspection(payload={}, command=None)
            raise self._command_error("inspection", error) from error
        try:
            payload = cast(JsonValue, json.loads(result.stdout))
        except json.JSONDecodeError as error:
            raise LabLifecycleError(
                "Containerlab returned invalid inspection JSON",
                operation="inspection",
                details={"stdout": result.stdout, "stderr": result.stderr},
            ) from error
        return LabInspection(
            payload=self._filter_lab(payload, self.topology_name(topology)), command=result
        )

    def require_absent_before_compile(self, site_dir: Path) -> None:
        """Refuse to replace build artifacts while their lab is still running."""
        topology = self.topology_path(site_dir)
        if not topology.is_file():
            return
        inspection = self.inspect(site_dir)
        if inspection.running:
            raise LabLifecycleError(
                "the lab already exists; destroy it before compiling a replacement build",
                operation="pre-compilation check",
            )

    def deploy(self, site_dir: Path, *, reconfigure: bool = False) -> LifecycleResult:
        """Deploy a validated build and prove that runtime resources exist."""
        topology = self.topology_path(site_dir)
        self._require_file(topology, operation="deployment")
        manifest = self._require_manifest_integrity(site_dir, operation="deployment")
        self._require_static_validation(site_dir)
        expected_nodes = self._expected_node_count(site_dir)
        expected_names = self.expected_container_names(topology)
        if len(expected_names) != expected_nodes:
            raise LabLifecycleError(
                "topology and inventory node counts do not match",
                operation="deployment",
            )
        before = self.inspect(site_dir)
        if before.running and not reconfigure:
            raise LabLifecycleError(
                "the lab already exists; pass reconfigure=True to replace its configuration",
                operation="deployment",
            )
        try:
            command = self._containerlab.deploy(topology, reconfigure=reconfigure)
        except CommandExecutionError as error:
            self._remove_deployment_stamp(site_dir)
            raise LabLifecycleError(
                str(error),
                operation="deployment",
                details={
                    "command": error.as_dict(),
                    "cleanup": self._cleanup_failed_deploy(topology),
                },
            ) from error
        try:
            after = self.inspect(site_dir)
        except LabLifecycleError as error:
            cleanup = self._cleanup_failed_deploy(topology)
            self._remove_deployment_stamp(site_dir)
            raise LabLifecycleError(
                f"post-deployment inspection failed: {error.message}",
                operation="deployment",
                details={"inspection": error.details, "cleanup": cleanup},
            ) from error
        observed_names = {
            name for node in after.nodes if isinstance((name := node.get("name")), str)
        }
        if observed_names != expected_names or not after.all_running:
            cleanup = self._cleanup_failed_deploy(topology)
            self._remove_deployment_stamp(site_dir)
            raise LabLifecycleError(
                "Containerlab did not report every expected node in the running state",
                operation="deployment",
                details={
                    "missing_nodes": sorted(expected_names - observed_names),
                    "unexpected_nodes": sorted(observed_names - expected_names),
                    "cleanup": cleanup,
                },
            )
        try:
            DeploymentStamp.from_build(site_dir, manifest).write(site_dir)
        except OSError as error:
            cleanup = self._cleanup_failed_deploy(topology)
            self._remove_deployment_stamp(site_dir)
            raise LabLifecycleError(
                "could not persist runtime deployment identity",
                operation="deployment",
                details={"path": (site_dir / DEPLOYMENT_STAMP_PATH).as_posix(), "cleanup": cleanup},
            ) from error
        return LifecycleResult(operation="deploy", changed=True, command=command, inspection=after)

    def destroy(
        self, site_dir: Path, *, cleanup: bool = True, ignore_missing: bool = True
    ) -> LifecycleResult:
        """Destroy only this build's lab and prove its resources are gone."""
        topology = self.topology_path(site_dir)
        self._require_file(topology, operation="destruction")
        before = self.inspect(site_dir)
        if not before.running and ignore_missing:
            self._remove_deployment_stamp(site_dir)
            return LifecycleResult(
                operation="destroy", changed=False, command=None, inspection=before
            )
        try:
            command = self._containerlab.destroy(topology, cleanup=cleanup)
        except CommandExecutionError as error:
            raise self._command_error("destruction", error) from error
        after = self.inspect(site_dir)
        if after.running:
            raise LabLifecycleError(
                "Containerlab still reports resources after destroy",
                operation="destruction",
            )
        self._remove_deployment_stamp(site_dir)
        return LifecycleResult(operation="destroy", changed=True, command=command, inspection=after)

    def require_deployed_build(self, site_dir: Path) -> DeploymentStamp:
        """Prove disk artifacts and the exact running lab share one build identity."""
        operation = "runtime identity validation"
        topology = self.topology_path(site_dir)
        self._require_file(topology, operation=operation)
        manifest = self._require_manifest_integrity(site_dir, operation=operation)
        stamp_path = site_dir / DEPLOYMENT_STAMP_PATH
        try:
            stamp = DeploymentStamp.model_validate_json(stamp_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise LabLifecycleError(
                "runtime deployment stamp is missing, unreadable, or invalid",
                operation=operation,
                details={"path": stamp_path.as_posix()},
            ) from error

        expected_names = tuple(sorted(self.expected_container_names(topology)))
        current_identity = {
            "lab_name": self.topology_name(topology),
            "topology_sha256": sha256_file(topology),
            "build_hash": manifest.build_hash,
            "source_revision": manifest.source_revision,
            "container_names": expected_names,
        }
        stamped_identity = {
            "lab_name": stamp.lab_name,
            "topology_sha256": stamp.topology_sha256,
            "build_hash": stamp.build_hash,
            "source_revision": stamp.source_revision,
            "container_names": stamp.container_names,
        }
        mismatches = sorted(
            key for key, value in current_identity.items() if stamped_identity[key] != value
        )
        if mismatches:
            raise LabLifecycleError(
                "running lab identity does not match the current compiled build",
                operation=operation,
                details={"mismatched_fields": mismatches},
            )

        inspection = self.inspect(site_dir)
        observed_names = tuple(
            sorted(name for node in inspection.nodes if isinstance((name := node.get("name")), str))
        )
        if not inspection.all_running or observed_names != stamp.container_names:
            raise LabLifecycleError(
                "running container set does not match the deployed build",
                operation=operation,
                details={
                    "expected_containers": list(stamp.container_names),
                    "observed_containers": list(observed_names),
                },
            )
        return stamp

    @staticmethod
    def _require_file(path: Path, *, operation: str) -> None:
        if not path.is_file():
            raise LabLifecycleError(
                f"required artifact does not exist: {path}",
                operation=operation,
                details={"path": path.as_posix()},
            )

    @staticmethod
    def _require_static_validation(site_dir: Path) -> None:
        report_path = site_dir / "reports" / "static-validation.json"
        if not report_path.is_file():
            raise LabLifecycleError(
                f"required static validation report does not exist: {report_path}",
                operation="deployment",
                details={"path": report_path.as_posix()},
            )
        try:
            report: object = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LabLifecycleError(
                "static validation report is unreadable or invalid",
                operation="deployment",
                details={"path": report_path.as_posix()},
            ) from error
        if (
            not isinstance(report, dict)
            or cast(dict[str, object], report).get("passed") is not True
        ):
            raise LabLifecycleError(
                "static validation has not passed",
                operation="deployment",
                details={"path": report_path.as_posix()},
            )

    @staticmethod
    def _expected_node_count(site_dir: Path) -> int:
        inventory_path = site_dir / "inventory.json"
        try:
            inventory: object = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise LabLifecycleError(
                "compiled inventory is unreadable or invalid",
                operation="deployment",
                details={"path": inventory_path.as_posix()},
            ) from error
        if not isinstance(inventory, dict):
            raise LabLifecycleError(
                "compiled inventory is not a JSON object",
                operation="deployment",
                details={"path": inventory_path.as_posix()},
            )
        count = cast(dict[str, object], inventory).get("node_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise LabLifecycleError(
                "compiled inventory has an invalid node count",
                operation="deployment",
                details={"path": inventory_path.as_posix()},
            )
        return count

    @staticmethod
    def _require_manifest_integrity(
        site_dir: Path, *, operation: str = "deployment"
    ) -> BuildManifest:
        manifest_path = site_dir / "manifest.json"
        try:
            manifest = BuildManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise LabLifecycleError(
                "build manifest is unreadable or invalid",
                operation=operation,
                details={"path": manifest_path.as_posix()},
            ) from error
        required = {
            "topology.clab.yml",
            "expected-state.json",
            "inventory.json",
            "reports/static-validation.json",
        }
        recorded = {artifact.path for artifact in manifest.files}
        if not required <= recorded:
            raise LabLifecycleError(
                "build manifest does not cover required deployment artifacts",
                operation=operation,
                details={"missing": sorted(required - recorded)},
            )
        for artifact in manifest.files:
            path = site_dir / artifact.path
            if (
                not path.is_file()
                or path.stat().st_size != artifact.size
                or sha256_file(path) != artifact.sha256
            ):
                raise LabLifecycleError(
                    f"build artifact differs from manifest: {artifact.path}",
                    operation=operation,
                    details={"path": artifact.path},
                )
        return manifest

    @staticmethod
    def _remove_deployment_stamp(site_dir: Path) -> None:
        stamp = site_dir / DEPLOYMENT_STAMP_PATH
        stamp.unlink(missing_ok=True)
        with suppress(OSError):
            stamp.parent.rmdir()

    @staticmethod
    def _command_error(operation: str, error: CommandExecutionError) -> LabLifecycleError:
        return LabLifecycleError(
            str(error),
            operation=operation,
            details={"command": error.as_dict()},
        )

    def _cleanup_failed_deploy(self, topology: Path) -> dict[str, object]:
        """Best-effort removal of resources created by a failed deployment."""
        try:
            result = self._containerlab.destroy(topology, cleanup=True)
        except CommandExecutionError as error:
            return {"attempted": True, "succeeded": False, "command": error.as_dict()}
        return {
            "attempted": True,
            "succeeded": result.succeeded,
            "returncode": result.returncode,
        }

    @staticmethod
    def _is_no_running_labs(error: CommandExecutionError) -> bool:
        """Recognize only Containerlab's explicit globally empty response."""
        stderr = error.stderr.lower()
        return (
            error.returncode == 1
            and error.kind is CommandFailureKind.NON_ZERO_EXIT
            and "no running containers" in stderr
        )

    @staticmethod
    def topology_name(topology: Path) -> str:
        """Read the Containerlab name from a generated topology."""
        try:
            payload: object = yaml.safe_load(topology.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise LabLifecycleError(
                "topology is unreadable or invalid",
                operation="inspection",
                details={"path": topology.as_posix()},
            ) from error
        if not isinstance(payload, dict):
            raise LabLifecycleError("topology is not a YAML object", operation="inspection")
        name = cast(dict[str, object], payload).get("name")
        if not isinstance(name, str) or not name:
            raise LabLifecycleError("topology has no lab name", operation="inspection")
        return name

    @classmethod
    def expected_container_names(cls, topology: Path) -> set[str]:
        """Derive the exact Containerlab container names for a topology."""
        try:
            payload: object = yaml.safe_load(topology.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise LabLifecycleError(
                "topology is unreadable or invalid", operation="deployment"
            ) from error
        if not isinstance(payload, dict):
            raise LabLifecycleError("topology is not a YAML object", operation="deployment")
        document = cast(dict[str, object], payload)
        topology_data = document.get("topology")
        if not isinstance(topology_data, dict):
            raise LabLifecycleError("topology has no node map", operation="deployment")
        nodes = cast(dict[str, object], topology_data).get("nodes")
        if not isinstance(nodes, dict):
            raise LabLifecycleError("topology has no node map", operation="deployment")
        lab_name = cls.topology_name(topology)
        return {f"clab-{lab_name}-{node}" for node in cast(dict[str, object], nodes)}

    @staticmethod
    def _filter_lab(payload: JsonValue, lab_name: str) -> JsonValue:
        """Select only this topology's records from global inspection output."""
        if isinstance(payload, dict):
            records = payload.get(lab_name, [])
            return {lab_name: records} if isinstance(records, list) else {}
        if isinstance(payload, list):
            records = [
                record
                for record in payload
                if isinstance(record, dict) and record.get("lab_name") == lab_name
            ]
            return cast(JsonValue, records)
        return {}
