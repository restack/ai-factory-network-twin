from pathlib import Path

import pytest
from pydantic import ValidationError

from aftwin.backend.capabilities import BackendCapability
from aftwin.domain.enums import FabricPlane
from aftwin.policy.profile import (
    DEFAULT_ENDPOINT_CAPABILITIES,
    DEFAULT_NETWORK_CAPABILITIES,
    load_policy_profile,
)


def test_golden_profile_requires_both_planes() -> None:
    profile = load_policy_profile(Path("config/policies/mini-dual-plane.yaml"))

    assert profile.required_planes == {FabricPlane.A, FabricPlane.B}
    assert profile.supported_network_platforms == {"frr"}
    assert profile.fabric_p2p_prefix_length == 31
    assert profile.host_p2p_prefix_length == 31
    assert profile.spine_count_by_plane == {FabricPlane.A: 2, FabricPlane.B: 2}
    assert profile.plane_address_pools[FabricPlane.A][0].prefixlen == 16


def test_profiles_default_to_the_baseline_capability_contract() -> None:
    profile = load_policy_profile(Path("config/policies/mini-dual-plane.yaml"))

    assert profile.required_network_capabilities == DEFAULT_NETWORK_CAPABILITIES
    assert profile.required_endpoint_capabilities == DEFAULT_ENDPOINT_CAPABILITIES
    assert BackendCapability.BGP_IPV4_UNICAST in profile.required_network_capabilities
    assert BackendCapability.VRF_ENDPOINT in profile.required_endpoint_capabilities


def test_profile_rejects_unknown_capability_values() -> None:
    profile = load_policy_profile(Path("config/policies/mini-dual-plane.yaml"))
    payload = profile.model_dump(mode="python")
    payload["required_network_capabilities"] = ["teleportation"]

    with pytest.raises(ValidationError):
        type(profile).model_validate(payload)


def test_smoke_profile_requires_only_plane_a() -> None:
    profile = load_policy_profile(Path("config/policies/smoke.yaml"))

    assert profile.required_planes == {FabricPlane.A}
    assert profile.spine_count_by_plane == {FabricPlane.A: 1}
    assert FabricPlane.B not in profile.plane_address_pools
