import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from aftwin.compiler.compiler import compile_fabric, load_platform_map
from aftwin.compiler.manifest import BuildManifest
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
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

    second = _compile(tmp_path)

    assert first == second
    assert runtime_file.exists()
    assert not runtime_report.exists()
    assert all(not item.path.startswith("clab-") for item in second.files)
    assert all(item.path != "reports/runtime-verification.json" for item in second.files)


def test_relative_output_directory_is_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    manifest = _compile(Path("build/aif-lab"))

    assert manifest.files
    assert (tmp_path / "build" / "aif-lab" / "manifest.json").is_file()


def test_topology_has_expected_shape_and_pinned_router_image(tmp_path: Path) -> None:
    _compile(tmp_path)
    topology = yaml.safe_load((tmp_path / "topology.clab.yml").read_text())

    assert topology["name"] == "mini-dual-plane"
    assert topology["mgmt"]["network"] == "aftwin-mgmt"
    assert topology["mgmt"]["ipv4-subnet"] == "172.30.30.0/24"
    assert len(topology["topology"]["nodes"]) == 12
    assert len(topology["topology"]["links"]) == 16
    assert "@sha256:" in topology["topology"]["nodes"]["spine-a1"]["image"]
    assert topology["topology"]["nodes"]["gpu01"]["exec"] == [
        "/bin/sh /usr/local/sbin/aftwin-endpoint-setup"
    ]


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

    assert {"expected-state.json", "inventory.json", "topology.clab.yml"} <= paths
    assert inventory["node_count"] == 12
    assert inventory["link_count"] == 16
