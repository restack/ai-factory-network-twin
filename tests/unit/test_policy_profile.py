from pathlib import Path

from aftwin.domain.enums import FabricPlane
from aftwin.policy.profile import load_policy_profile


def test_golden_profile_requires_both_planes() -> None:
    profile = load_policy_profile(Path("config/policies/mini-dual-plane.yaml"))

    assert profile.required_planes == {FabricPlane.A, FabricPlane.B}
    assert profile.supported_network_platforms == {"frr"}
    assert profile.fabric_p2p_prefix_length == 31
    assert profile.host_p2p_prefix_length == 31
    assert profile.spine_count_by_plane == {FabricPlane.A: 2, FabricPlane.B: 2}
    assert profile.plane_address_pools[FabricPlane.A][0].prefixlen == 16


def test_smoke_profile_requires_only_plane_a() -> None:
    profile = load_policy_profile(Path("config/policies/smoke.yaml"))

    assert profile.required_planes == {FabricPlane.A}
    assert profile.spine_count_by_plane == {FabricPlane.A: 1}
    assert FabricPlane.B not in profile.plane_address_pools
