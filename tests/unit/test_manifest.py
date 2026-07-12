import json
from pathlib import Path

import pytest

from aftwin.compiler.manifest import (
    BuildManifest,
    FileDigest,
    InventoryMetadata,
    collect_artifact_digests,
    sha256_bytes,
    sha256_file,
)
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture


def _build_tree(root: Path) -> None:
    (root / "configs" / "routers" / "spine-a1").mkdir(parents=True)
    (root / "configs" / "routers" / "spine-a1" / "frr.conf").write_text(
        "router bgp 65001\n", encoding="utf-8", newline="\n"
    )
    (root / "topology.clab.yml").write_text(
        "name: mini-dual-plane\n", encoding="utf-8", newline="\n"
    )


def test_hash_helpers_and_paths_are_content_based_and_stably_sorted(tmp_path: Path) -> None:
    _build_tree(tmp_path)

    digests = collect_artifact_digests(tmp_path)

    assert [digest.path for digest in digests] == [
        "configs/routers/spine-a1/frr.conf",
        "topology.clab.yml",
    ]
    assert all("\\" not in digest.path for digest in digests)
    topology = tmp_path / "topology.clab.yml"
    assert sha256_file(topology) == sha256_bytes(topology.read_bytes())


def test_manifest_repeated_creation_and_write_are_byte_identical(tmp_path: Path) -> None:
    _build_tree(tmp_path)

    first = BuildManifest.create(
        tmp_path,
        compiler_version="0.1.0-test",
        source_revision="source-revision",
    )
    first_path = first.write(tmp_path)
    first_bytes = first_path.read_bytes()
    second = BuildManifest.create(
        tmp_path,
        compiler_version="0.1.0-test",
        source_revision="source-revision",
    )
    second.write(tmp_path)

    assert first == second
    assert first_bytes == (tmp_path / "manifest.json").read_bytes()
    assert first.to_json().endswith("\n")
    assert all(file.path != "manifest.json" for file in first.files)
    assert "timestamp" not in first.to_json().lower()
    assert "random" not in first.to_json().lower()


def test_manifest_hash_changes_when_artifact_content_changes(tmp_path: Path) -> None:
    _build_tree(tmp_path)
    before = BuildManifest.create(tmp_path, source_revision="source-revision")

    (tmp_path / "topology.clab.yml").write_text("name: changed\n", encoding="utf-8", newline="\n")
    after = BuildManifest.create(tmp_path, source_revision="source-revision")

    assert before.build_hash != after.build_hash
    assert before.files != after.files


def test_manifest_identity_includes_compiler_and_source_revisions(tmp_path: Path) -> None:
    _build_tree(tmp_path)

    baseline = BuildManifest.create(tmp_path, compiler_version="1.0", source_revision="source-a")
    compiler_changed = BuildManifest.create(
        tmp_path, compiler_version="2.0", source_revision="source-a"
    )
    source_changed = BuildManifest.create(
        tmp_path, compiler_version="1.0", source_revision="source-b"
    )

    assert len({baseline.build_hash, compiler_changed.build_hash, source_changed.build_hash}) == 3


def test_artifacts_outside_build_root_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "build"
    root.mkdir()
    outside = tmp_path / "outside.conf"
    outside.write_text("external\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside build root"):
        FileDigest.from_path(root, outside)


def test_inventory_metadata_is_stable_newline_json() -> None:
    fabric = fixture_to_fabric(load_fixture(Path("fixtures/mini-dual-plane.yaml")))

    first = InventoryMetadata.from_fabric(fabric, compiler_version="0.1.0-test")
    second = InventoryMetadata.from_fabric(fabric, compiler_version="0.1.0-test")
    payload = json.loads(first.to_json())

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().endswith("\n")
    assert payload == {
        "compiler_version": "0.1.0-test",
        "fabric_name": "mini-dual-plane",
        "link_count": 16,
        "node_count": 12,
        "schema_version": 1,
        "site": "aif-lab",
        "source_revision": fabric.source_revision,
    }
