"""Validated intent to deterministic deployable artifacts."""

import re
import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aftwin.compiler.expected_state import generate_expected_state, render_expected_state
from aftwin.compiler.manifest import BuildManifest, InventoryMetadata
from aftwin.domain.enums import NodeRole
from aftwin.domain.models import Fabric
from aftwin.render.containerlab import render_containerlab_topology
from aftwin.render.endpoint import render_endpoint_setup
from aftwin.render.frr import DAEMONS, render_frr_config


class PlatformEntry(BaseModel):
    """One Git-owned platform-to-runtime mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1)
    image: str = Field(min_length=1)
    renderer: Literal["frr", "linux_endpoint"]

    @field_validator("image")
    @classmethod
    def require_version_tag(cls, value: str) -> str:
        reference = value.partition("@")[0]
        component = reference.rsplit("/", maxsplit=1)[-1]
        _, separator, tag = component.rpartition(":")
        if not separator or re.fullmatch(r"v?[0-9]+(?:[._-][A-Za-z0-9]+)*", tag) is None:
            raise ValueError("runtime image must use an explicit version tag")
        return value


class PlatformMap(BaseModel):
    """Versioned platform mappings used by the compiler."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    platforms: dict[str, PlatformEntry]


class CompileResult(BaseModel):
    """Stable public summary of a successful compilation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    site: str
    fabric: str
    output_dir: Path
    node_count: int
    link_count: int
    build_hash: str


def load_platform_map(path: Path) -> PlatformMap:
    """Load and strictly validate the Git-owned platform map."""
    with path.open(encoding="utf-8") as stream:
        payload: object = yaml.safe_load(stream)
    return PlatformMap.model_validate(payload)


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    if executable:
        path.chmod(0o755)


def _clear_generated(root: Path) -> None:
    for relative in (
        "configs",
        "topology.clab.yml",
        "expected-state.json",
        "inventory.json",
        "runtime-images.json",
        "manifest.json",
    ):
        path = root / relative
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    runtime_report = root / "reports" / "runtime-verification.json"
    if runtime_report.exists():
        runtime_report.unlink()
    scenario_reports = root / "reports" / "scenarios"
    if scenario_reports.is_dir():
        shutil.rmtree(scenario_reports)


def _manifest_paths(root: Path) -> tuple[Path, ...]:
    """Select compiler pipeline outputs while excluding runtime working state."""
    root = root.resolve()
    paths = [
        root / "topology.clab.yml",
        root / "expected-state.json",
        root / "inventory.json",
    ]
    for directory in (root / "configs", root / "source"):
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    static_report = root / "reports" / "static-validation.json"
    if static_report.is_file():
        paths.append(static_report)
    return tuple(paths)


def compile_fabric(
    fabric: Fabric,
    platform_map: PlatformMap,
    profile: object,
    output_dir: Path,
) -> CompileResult:
    """Compile an already validated fabric without invoking any runtime."""
    # Importing the concrete type here would not add runtime safety; generation validates it.
    from aftwin.policy.profile import PolicyProfile

    if not isinstance(profile, PolicyProfile):
        raise TypeError("profile must be a PolicyProfile")
    # ``model_copy(update=...)`` does not revalidate Pydantic models. Revalidate
    # at the filesystem boundary so externally sourced identifiers cannot
    # escape the build root when they become directory names.
    fabric = Fabric.model_validate(fabric.model_dump(mode="python"))
    required = {node.platform for node in fabric.nodes}
    unsupported = sorted(required - set(platform_map.platforms))
    if unsupported:
        raise ValueError(f"unsupported platforms: {', '.join(unsupported)}")
    for node in fabric.nodes:
        mapping = platform_map.platforms[node.platform]
        expected_renderer = "linux_endpoint" if node.role is NodeRole.COMPUTE else "frr"
        if mapping.renderer != expected_renderer:
            raise ValueError(
                f"platform {node.platform!r} uses renderer {mapping.renderer!r}; "
                f"node {node.name!r} requires {expected_renderer!r}"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated(output_dir)
    expected = generate_expected_state(fabric, profile)
    mappings = {
        name: {"kind": entry.kind, "image": entry.image, "renderer": entry.renderer}
        for name, entry in platform_map.platforms.items()
    }
    _write(output_dir / "topology.clab.yml", render_containerlab_topology(fabric, mappings))
    for node in sorted(fabric.nodes, key=lambda item: item.name):
        if node.role is NodeRole.COMPUTE:
            _write(
                output_dir / "configs" / "endpoints" / node.name / "setup.sh",
                render_endpoint_setup(node, expected.endpoint_prefixes),
                executable=True,
            )
        else:
            router_dir = output_dir / "configs" / "routers" / node.name
            _write(router_dir / "daemons", DAEMONS)
            _write(router_dir / "frr.conf", render_frr_config(fabric, node))

    _write(output_dir / "expected-state.json", render_expected_state(expected))
    _write(output_dir / "inventory.json", InventoryMetadata.from_fabric(fabric).to_json())
    manifest = BuildManifest.create(
        output_dir,
        source_revision=fabric.source_revision,
        paths=_manifest_paths(output_dir),
    )
    manifest.write(output_dir)
    return CompileResult(
        site=fabric.site,
        fabric=fabric.name,
        output_dir=output_dir,
        node_count=len(fabric.nodes),
        link_count=len(fabric.links),
        build_hash=manifest.build_hash,
    )
