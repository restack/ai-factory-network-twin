from pathlib import Path

import pytest

from aftwin.backend.capabilities import BackendCapability
from aftwin.backend.contract import BackendRoleClass, GeneratedFile
from aftwin.backend.registry import get_backend, registered_renderers
from aftwin.compiler.compiler import PlatformEntry, compile_fabric, load_platform_map
from aftwin.compiler.expected_state import generate_expected_state
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.profile import load_policy_profile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "fixtures/mini-dual-plane.yaml"
PROFILE = PROJECT_ROOT / "config/policies/mini-dual-plane.yaml"
PLATFORMS = PROJECT_ROOT / "config/platform-map.yaml"


def test_registry_resolves_declared_backends() -> None:
    frr = get_backend("frr")
    endpoint = get_backend("linux_endpoint")

    assert {"frr", "linux_endpoint"} <= registered_renderers()
    assert frr.role_class is BackendRoleClass.NETWORK
    assert endpoint.role_class is BackendRoleClass.ENDPOINT
    assert BackendCapability.BGP_IPV4_UNICAST in frr.capabilities
    assert BackendCapability.ECMP_MULTIPATH in frr.capabilities
    assert BackendCapability.VRF_ENDPOINT in endpoint.capabilities


def test_registry_rejects_unknown_renderer_with_supported_set() -> None:
    with pytest.raises(ValueError, match=r"unsupported renderer.*supported renderers"):
        get_backend("does-not-exist")


def test_platform_entry_rejects_unregistered_renderer() -> None:
    with pytest.raises(ValueError, match="unsupported renderer"):
        PlatformEntry(kind="linux", image="quay.io/frrouting/frr:10.3.4", renderer="nonsense")


def test_default_backends_use_identity_interface_mapping() -> None:
    assert get_backend("frr").runtime_interface_name("eth1") == "eth1"
    assert get_backend("linux_endpoint").runtime_interface_name("eth2") == "eth2"


def test_generated_file_rejects_escaping_paths() -> None:
    with pytest.raises(ValueError, match="relative POSIX path"):
        GeneratedFile(path="../escape.conf", content="x\n")
    with pytest.raises(ValueError, match="relative POSIX path"):
        GeneratedFile(path="/absolute.conf", content="x\n")


def test_backend_renderers_cover_every_fixture_node() -> None:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    profile = load_policy_profile(PROFILE)
    expected = generate_expected_state(fabric, profile)

    for node in fabric.nodes:
        renderer = "frr" if node.role.value.startswith("fabric-") else "linux_endpoint"
        artifacts = get_backend(renderer).render_node(fabric, node, expected)
        assert artifacts
        assert all(artifact.path.startswith("configs/") for artifact in artifacts)


def test_compile_rejects_unsatisfied_capability_requirements(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    profile = load_policy_profile(PROFILE).model_copy(
        update={
            "required_endpoint_capabilities": frozenset(
                {BackendCapability.VRF_ENDPOINT, BackendCapability.BGP_IPV4_UNICAST}
            )
        }
    )

    with pytest.raises(ValueError, match=r"capability requirements.*linux_endpoint.*lacks"):
        compile_fabric(fabric, load_platform_map(PLATFORMS), profile, tmp_path)

    assert not (tmp_path / "topology.clab.yml").exists()


def test_compile_rejects_role_class_mismatch(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(FIXTURE))
    platform_map = load_platform_map(PLATFORMS)
    platforms = dict(platform_map.platforms)
    platforms["frr"] = platforms["frr"].model_copy(update={"renderer": "linux_endpoint"})
    broken = platform_map.model_copy(update={"platforms": platforms})

    with pytest.raises(ValueError, match="requires a network renderer"):
        compile_fabric(fabric, broken, load_policy_profile(PROFILE), tmp_path)
