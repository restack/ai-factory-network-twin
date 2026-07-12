from pathlib import Path

import pytest
from pydantic import ValidationError

from aftwin.compiler.expected_state import (
    ExpectedState,
    generate_expected_state,
    render_expected_state,
)
from aftwin.domain.enums import FabricPlane
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.profile import load_policy_profile

FIXTURE_PATH = Path("fixtures/mini-dual-plane.yaml")
PROFILE_PATH = Path("config/policies/mini-dual-plane.yaml")


def _expected_state() -> ExpectedState:
    fabric = fixture_to_fabric(load_fixture(FIXTURE_PATH))
    profile = load_policy_profile(PROFILE_PATH)
    return generate_expected_state(fabric, profile)


def test_golden_expected_state_counts_and_runtime_metadata() -> None:
    state = _expected_state()

    assert len(state.bgp_adjacencies) == 8
    assert len(state.endpoint_prefixes) == 8
    assert len(state.router_prefixes) == 32
    assert len(state.reachability) == 24
    assert len(state.isolation) == 2
    for plane in (FabricPlane.A, FabricPlane.B):
        assert sum(adjacency.plane is plane for adjacency in state.bgp_adjacencies) == 4
        assert sum(endpoint.plane is plane for endpoint in state.endpoint_prefixes) == 4
        assert sum(probe.plane is plane for probe in state.reachability) == 12

    assert state.bgp_adjacencies[0].leaf.node == "leaf-a1"
    assert str(state.bgp_adjacencies[0].leaf.address) == "10.0.0.1"
    assert state.bgp_adjacencies[0].leaf.asn == 65_101
    assert state.bgp_adjacencies[0].spine.node == "spine-a1"
    assert str(state.endpoint_prefixes[0].prefix) == "10.0.1.0/31"
    assert state.endpoint_prefixes[0].vrf == "fabric-a"

    connected = [route for route in state.router_prefixes if route.protocol == "connected"]
    remote_leaf = [
        route
        for route in state.router_prefixes
        if route.protocol == "bgp" and route.router.startswith("leaf-")
    ]
    spine = [route for route in state.router_prefixes if route.router.startswith("spine-")]
    assert len(connected) == 8
    assert len(remote_leaf) == 8
    assert len(spine) == 16
    assert {route.min_next_hops for route in remote_leaf} == {2}
    assert {route.min_next_hops for route in spine} == {1}

    plane_a_isolation = state.isolation[0]
    assert plane_a_isolation.source_plane is FabricPlane.A
    assert plane_a_isolation.destination_plane is FabricPlane.B
    assert plane_a_isolation.source_nodes == ("gpu01", "gpu02", "gpu03", "gpu04")
    assert tuple(map(str, plane_a_isolation.blocked_endpoint_addresses)) == (
        "10.1.1.1",
        "10.1.1.3",
        "10.1.1.5",
        "10.1.1.7",
    )


def test_expected_state_json_is_deterministic_and_round_trips() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    fabric = fixture_to_fabric(fixture)
    reordered = fabric.model_copy(
        update={
            "nodes": tuple(reversed(fabric.nodes)),
            "links": tuple(
                link.model_copy(
                    update={
                        "endpoint_a": link.endpoint_b,
                        "endpoint_b": link.endpoint_a,
                    }
                )
                for link in reversed(fabric.links)
            ),
        }
    )
    profile = load_policy_profile(PROFILE_PATH)

    first = render_expected_state(generate_expected_state(fabric, profile))
    second = render_expected_state(generate_expected_state(reordered, profile))

    assert first == second
    assert first.endswith("\n")
    assert ExpectedState.model_validate_json(first) == generate_expected_state(fabric, profile)


def test_expected_state_models_are_strict_and_immutable() -> None:
    state = _expected_state()

    with pytest.raises(ValidationError, match="frozen"):
        state.__setattr__("fabric", "changed")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ExpectedState.model_validate({**state.model_dump(), "unexpected": True})
