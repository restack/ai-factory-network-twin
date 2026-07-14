"""Deterministic inventory metadata and build manifests."""

import hashlib
import json
from collections.abc import Iterable, Mapping
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aftwin import __version__
from aftwin.domain.models import Fabric

SHA256_PATTERN = r"^[0-9a-f]{64}$"
DEFAULT_MANIFEST_PATH = "manifest.json"


def sha256_bytes(content: bytes) -> str:
    """Return the lowercase SHA-256 digest for ``content``."""
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file without depending on its metadata or platform newlines."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _canonical_input(value: Any) -> Any:
    """Normalize typed model data, including unordered sets, for stable hashing."""
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key.value if isinstance(key, Enum) else key): _canonical_input(item)
            for key, item in mapping.items()
        }
    if isinstance(value, (set, frozenset)):
        values = cast(set[object] | frozenset[object], value)
        normalized = [_canonical_input(item) for item in values]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        values = cast(list[object] | tuple[object, ...], value)
        return [_canonical_input(item) for item in values]
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _relative_path(root: Path, path: str | Path) -> tuple[str, Path]:
    resolved_root = root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    resolved_candidate = candidate.resolve()
    try:
        relative = resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ValueError(f"artifact path is outside build root: {path}") from error
    if not resolved_candidate.is_file():
        raise ValueError(f"artifact path is not a file: {path}")
    return PurePosixPath(*relative.parts).as_posix(), resolved_candidate


class FileDigest(BaseModel):
    """Content identity for one generated artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def require_relative_posix_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("artifact path must be a normalized relative POSIX path")
        return value

    @classmethod
    def from_path(cls, root: Path, path: str | Path) -> Self:
        """Create a digest using a path relative to ``root``."""
        relative, resolved = _relative_path(root, path)
        return cls(path=relative, sha256=sha256_file(resolved), size=resolved.stat().st_size)


def collect_artifact_digests(
    root: Path,
    paths: Iterable[str | Path] | None = None,
    *,
    exclude: Iterable[str] = (DEFAULT_MANIFEST_PATH,),
) -> tuple[FileDigest, ...]:
    """Hash artifacts under ``root`` in stable relative-path order.

    The manifest excludes itself by default, so repeated collection after a
    manifest write has the same identity as collection before that write.
    """
    resolved_root = root.resolve()
    if paths is None:
        candidates: Iterable[str | Path] = (
            path for path in resolved_root.rglob("*") if path.is_file()
        )
    else:
        candidates = paths
    excluded = {PurePosixPath(path).as_posix() for path in exclude}
    by_path: dict[str, FileDigest] = {}
    for candidate in candidates:
        digest = FileDigest.from_path(resolved_root, candidate)
        if digest.path not in excluded:
            by_path[digest.path] = digest
    return tuple(by_path[path] for path in sorted(by_path))


class InventoryNodeRecord(BaseModel):
    """One compiled node's platform and renderer binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    renderer: str = Field(min_length=1)


class InventoryMetadata(BaseModel):
    """Stable build provenance and inventory counts for ``inventory.json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=2, ge=1)
    compiler_version: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    fabric_name: str = Field(min_length=1)
    site: str = Field(min_length=1)
    node_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    nodes: tuple[InventoryNodeRecord, ...] = ()

    @classmethod
    def from_fabric(
        cls,
        fabric: Fabric,
        *,
        renderers: Mapping[str, str],
        compiler_version: str = __version__,
    ) -> Self:
        """Create deterministic inventory metadata from normalized intent."""
        missing = sorted({node.platform for node in fabric.nodes} - set(renderers))
        if missing:
            raise ValueError(f"platforms without a renderer binding: {', '.join(missing)}")
        return cls(
            compiler_version=compiler_version,
            source_revision=fabric.source_revision,
            fabric_name=fabric.name,
            site=fabric.site,
            node_count=len(fabric.nodes),
            link_count=len(fabric.links),
            nodes=tuple(
                InventoryNodeRecord(
                    name=node.name,
                    role=node.role.value,
                    platform=node.platform,
                    renderer=renderers[node.platform],
                )
                for node in sorted(fabric.nodes, key=lambda item: item.name)
            ),
        )

    def to_json(self) -> str:
        """Render canonical newline-terminated JSON."""
        return _canonical_json(self.model_dump(mode="json"))


class BuildInputIdentity(BaseModel):
    """Stable semantic identity for one Git-owned compiler input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)

    @classmethod
    def from_payload(cls, name: str, payload: Mapping[str, Any]) -> Self:
        """Hash a validated input's canonical JSON representation."""
        content = _canonical_json(_canonical_input(payload)).encode("utf-8")
        return cls(name=name, sha256=sha256_bytes(content))


UNSPECIFIED_INPUT = BuildInputIdentity(
    name="unspecified",
    sha256=sha256_bytes(b""),
)


class BuildManifest(BaseModel):
    """Content-derived identity of one complete compiler output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2] = 2
    compiler_version: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    policy_profile: BuildInputIdentity = UNSPECIFIED_INPUT
    platform_map: BuildInputIdentity = UNSPECIFIED_INPUT
    build_hash: str = Field(pattern=SHA256_PATTERN)
    files: tuple[FileDigest, ...]

    @field_validator("files")
    @classmethod
    def sort_and_require_unique_files(cls, files: tuple[FileDigest, ...]) -> tuple[FileDigest, ...]:
        ordered = tuple(sorted(files, key=lambda item: item.path))
        if len({file.path for file in ordered}) != len(ordered):
            raise ValueError("manifest file paths must be unique")
        return ordered

    @classmethod
    def create(
        cls,
        root: Path,
        *,
        source_revision: str,
        policy_profile: BuildInputIdentity = UNSPECIFIED_INPUT,
        platform_map: BuildInputIdentity = UNSPECIFIED_INPUT,
        compiler_version: str = __version__,
        paths: Iterable[str | Path] | None = None,
        schema_version: Literal[2] = 2,
    ) -> Self:
        """Hash compiler artifacts and derive a non-self-referential build ID."""
        files = collect_artifact_digests(root, paths)
        identity = {
            "schema_version": schema_version,
            "compiler_version": compiler_version,
            "source_revision": source_revision,
            "policy_profile": policy_profile.model_dump(mode="json"),
            "platform_map": platform_map.model_dump(mode="json"),
            "files": [file.model_dump(mode="json") for file in files],
        }
        build_hash = sha256_bytes(_canonical_json(identity).encode("utf-8"))
        return cls(
            schema_version=schema_version,
            compiler_version=compiler_version,
            source_revision=source_revision,
            policy_profile=policy_profile,
            platform_map=platform_map,
            build_hash=build_hash,
            files=files,
        )

    def to_json(self) -> str:
        """Render canonical newline-terminated JSON."""
        return _canonical_json(self.model_dump(mode="json"))

    def write(self, root: Path, path: str | Path = DEFAULT_MANIFEST_PATH) -> Path:
        """Write the manifest below ``root`` and return its resolved path."""
        resolved_root = root.resolve()
        destination = Path(path)
        if not destination.is_absolute():
            destination = resolved_root / destination
        resolved_destination = destination.resolve()
        try:
            resolved_destination.relative_to(resolved_root)
        except ValueError as error:
            raise ValueError(f"manifest path is outside build root: {path}") from error
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        resolved_destination.write_text(self.to_json(), encoding="utf-8", newline="\n")
        return resolved_destination
