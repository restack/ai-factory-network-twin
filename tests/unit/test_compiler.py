import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from aftwin.compiler.compiler import (
    PlatformEntry,
    compile_fabric,
    load_platform_map,
)
from aftwin.compiler.manifest import BuildManifest
from aftwin.domain.enums import NodeRole
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.engine import PolicyEngine
from aftwin.policy.profile import load_policy_profile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "fixtures/mini-dual-plane.yaml"
PROFILE = PROJECT_ROOT / "config/policies/mini-dual-plane.yaml"
PLATFORMS = PROJECT_ROOT / "config/platform-map.yaml"
GOLDEN = PROJECT_ROOT / "tests/golden/mini-dual-plane"


def _compile(output: Path) -> BuildManifest:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    result = compile_fabric(
        fabric,
        load_platform_map(PLATFORMS),
        load_policy_profile(PROFILE),
        output,
    )
    manifest = BuildManifest.model_validate_json((output / "manifest.json").read_text())
    assert result.build_hash == manifest.build_hash
    return manifest


def _content_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_compilation_is_byte_deterministic_and_clears_stale_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "build"
    first = _compile(output)
    first_tree = _content_tree(output)
    stale = output / "configs" / "routers" / "removed" / "frr.conf"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale\n")

    second = _compile(output)

    assert first == second
    assert first_tree == _content_tree(output)
    assert not stale.exists()
    assert len(first.files) == 23


def test_runtime_working_files_do_not_change_compiler_identity(tmp_path: Path) -> None:
    first = _compile(tmp_path)
    runtime_file = tmp_path / "clab-mini-dual-plane" / "graph" / "topology.clab.mermaid"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("runtime output\n")
    runtime_report = tmp_path / "reports" / "runtime-verification.json"
    runtime_report.parent.mkdir()
    runtime_report.write_text('{"passed": true}\n')
    stale_scenario = tmp_path / "reports" / "scenarios" / "old-build.json"
    stale_scenario.parent.mkdir()
    stale_scenario.write_text('{"passed": true}\n')
    legacy_runtime_images = tmp_path / "runtime-images.json"
    legacy_runtime_images.write_text('{"schema_version": 1}\n')

    second = _compile(tmp_path)

    assert first == second
    assert runtime_file.exists()
    assert not runtime_report.exists()
    assert not stale_scenario.exists()
    assert not legacy_runtime_images.exists()
    assert all(not item.path.startswith("clab-") for item in second.files)
    assert all(item.path != "reports/runtime-verification.json" for item in second.files)


def test_compiler_revalidates_identifiers_before_writing_paths(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    unsafe_name = "../../../escaped"
    nodes = tuple(
        node.model_copy(update={"name": unsafe_name}) if node.name == "spine-a1" else node
        for node in fabric.nodes
    )
    links = tuple(
        link.model_copy(
            update={
                "endpoint_a": (
                    link.endpoint_a.model_copy(update={"node": unsafe_name})
                    if link.endpoint_a.node == "spine-a1"
                    else link.endpoint_a
                ),
                "endpoint_b": (
                    link.endpoint_b.model_copy(update={"node": unsafe_name})
                    if link.endpoint_b.node == "spine-a1"
                    else link.endpoint_b
                ),
            }
        )
        for link in fabric.links
    )
    unsafe = fabric.model_copy(update={"nodes": nodes, "links": links})
    output = tmp_path / "build"

    with pytest.raises(ValueError, match="String should match pattern"):
        compile_fabric(
            unsafe,
            load_platform_map(PLATFORMS),
            load_policy_profile(PROFILE),
            output,
        )

    assert not (tmp_path / "escaped").exists()


def test_relative_output_directory_is_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    manifest = _compile(Path("build/aif-lab"))

    assert manifest.files
    assert (tmp_path / "build" / "aif-lab" / "manifest.json").is_file()


def test_topology_has_expected_shape_and_versioned_images(tmp_path: Path) -> None:
    _compile(tmp_path)
    topology = yaml.safe_load((tmp_path / "topology.clab.yml").read_text())

    assert topology["name"] == "mini-dual-plane"
    assert topology["mgmt"]["network"] == "aftwin-mgmt"
    assert topology["mgmt"]["ipv4-subnet"] == "172.30.30.0/24"
    assert len(topology["topology"]["nodes"]) == 12
    assert len(topology["topology"]["links"]) == 16
    assert topology["topology"]["nodes"]["spine-a1"]["image"] == ("quay.io/frrouting/frr:10.3.4")
    assert topology["topology"]["nodes"]["spine-a1"]["group"] == "spine"
    assert topology["topology"]["nodes"]["leaf-a1"]["group"] == "leaf"
    assert topology["topology"]["nodes"]["gpu01"]["exec"] == [
        "/bin/sh /usr/local/sbin/aftwin-endpoint-setup"
    ]
    assert topology["topology"]["nodes"]["gpu01"]["image"] == "aftwin-endpoint:0.1.0"
    assert topology["topology"]["nodes"]["gpu01"]["group"] == "server"


def test_generated_topology_is_accepted_by_containerlab_offline(tmp_path: Path) -> None:
    executable = shutil.which("containerlab")
    if executable is None:
        pytest.skip("containerlab is not installed")
    _compile(tmp_path)

    result = subprocess.run(
        [executable, "graph", "--offline", "--mermaid", "-t", str(tmp_path / "topology.clab.yml")],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_compiler_output_matches_committed_golden_tree(tmp_path: Path) -> None:
    _compile(tmp_path)

    assert _content_tree(tmp_path) == _content_tree(GOLDEN)


def test_manifest_covers_expected_state_and_inventory(tmp_path: Path) -> None:
    manifest = _compile(tmp_path)
    paths = {item.path for item in manifest.files}
    inventory = json.loads((tmp_path / "inventory.json").read_text())

    assert {
        "expected-state.json",
        "inventory.json",
        "topology.clab.yml",
    } <= paths
    assert inventory["node_count"] == 12
    assert inventory["link_count"] == 16


def test_manifest_identifies_policy_profile_and_platform_map_content(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    profile = load_policy_profile(PROFILE)
    platform_map = load_platform_map(PLATFORMS)
    baseline_dir = tmp_path / "baseline"
    custom_dir = tmp_path / "custom"

    compile_fabric(fabric, platform_map, profile, baseline_dir)
    custom_profile = profile.model_copy(update={"name": "custom-profile"})
    custom_platforms = dict(platform_map.platforms)
    custom_platforms["frr"] = custom_platforms["frr"].model_copy(
        update={"image": "quay.io/frrouting/frr:10.3.5"}
    )
    custom_platform_map = platform_map.model_copy(update={"platforms": custom_platforms})
    compile_fabric(fabric, custom_platform_map, custom_profile, custom_dir)

    baseline = BuildManifest.model_validate_json((baseline_dir / "manifest.json").read_text())
    custom = BuildManifest.model_validate_json((custom_dir / "manifest.json").read_text())
    assert baseline.schema_version == 2
    assert baseline.policy_profile.name == "mini-dual-plane"
    assert baseline.platform_map.name == "platform-map-v1"
    assert baseline.policy_profile.sha256 != custom.policy_profile.sha256
    assert baseline.platform_map.sha256 != custom.platform_map.sha256
    assert baseline.build_hash != custom.build_hash


def test_storage_endpoint_passes_policy_and_compiles(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    nodes = tuple(
        node.model_copy(update={"role": NodeRole.STORAGE}) if node.name == "gpu01" else node
        for node in fabric.nodes
    )
    storage_fabric = fabric.model_copy(update={"nodes": nodes})
    profile = load_policy_profile(PROFILE)

    report = PolicyEngine().validate(storage_fabric, profile)
    result = compile_fabric(
        storage_fabric,
        load_platform_map(PLATFORMS),
        profile,
        tmp_path,
    )
    topology = yaml.safe_load((tmp_path / "topology.clab.yml").read_text())
    expected = json.loads((tmp_path / "expected-state.json").read_text())

    assert report.passed
    assert result.node_count == 12
    assert (tmp_path / "configs/endpoints/gpu01/setup.sh").is_file()
    assert not (tmp_path / "configs/routers/gpu01").exists()
    assert topology["topology"]["nodes"]["gpu01"]["group"] == "server"
    assert sum(item["node"] == "gpu01" for item in expected["endpoint_prefixes"]) == 2


@pytest.mark.parametrize(
    "image",
    ("frrouting/frr:latest", "frrouting/frr", "frrouting/frr:stable"),
)
def test_platform_map_rejects_images_without_version_tag(image: str) -> None:
    with pytest.raises(ValueError, match="explicit version tag"):
        PlatformEntry(kind="linux", image=image, renderer="frr")


@pytest.mark.parametrize(
    "image",
    ("quay.io/frrouting/frr:10.3.4", "postgres:18-alpine", "aftwin-endpoint:0.1.0"),
)
def test_platform_map_accepts_compatible_version_tags(image: str) -> None:
    assert PlatformEntry(kind="linux", image=image, renderer="frr").image == image
