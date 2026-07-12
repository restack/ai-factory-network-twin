"""Tests for strict deterministic failure-scenario definitions."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from aftwin.domain.enums import FabricPlane
from aftwin.scenario.models import FailureScenario, ScenarioType, load_scenario

SCENARIOS = Path("scenarios")


@pytest.mark.parametrize(
    ("filename", "scenario_type", "node", "interfaces"),
    [
        ("link-failure.yaml", ScenarioType.LINK_DOWN, "leaf-a1", ("eth1",)),
        ("spine-failure.yaml", ScenarioType.SPINE_DOWN, "spine-a1", ()),
    ],
)
def test_repository_scenarios_are_valid(
    filename: str,
    scenario_type: ScenarioType,
    node: str,
    interfaces: tuple[str, ...],
) -> None:
    scenario = load_scenario(SCENARIOS / filename)

    assert scenario.failure.type is scenario_type
    assert scenario.failure.target.node == node
    assert scenario.failure.target.interfaces == interfaces
    assert scenario.expected.surviving_planes == (FabricPlane.A, FabricPlane.B)
    assert {probe.plane for probe in scenario.expected.probes} == {
        FabricPlane.A,
        FabricPlane.B,
    }


def test_scenario_collections_are_canonicalized() -> None:
    scenario = FailureScenario.model_validate(
        {
            "name": "ordered",
            "description": "Canonical ordering",
            "failure": {
                "type": "link-down",
                "target": {"node": "leaf-a1", "interfaces": ["eth2"]},
            },
            "expected": {
                "surviving_planes": ["b", "a"],
                "probes": [
                    {"plane": "b", "source_node": "gpu02", "destination_node": "gpu04"},
                    {"plane": "a", "source_node": "gpu02", "destination_node": "gpu04"},
                ],
            },
        }
    )

    assert scenario.expected.surviving_planes == (FabricPlane.A, FabricPlane.B)
    assert tuple(probe.plane for probe in scenario.expected.probes) == (
        FabricPlane.A,
        FabricPlane.B,
    )


@pytest.mark.parametrize(
    "failure",
    [
        {"type": "link-down", "target": {"node": "leaf-a1"}},
        {
            "type": "link-down",
            "target": {"node": "leaf-a1", "interfaces": ["eth1", "eth2"]},
        },
        {
            "type": "spine-down",
            "target": {"node": "spine-a1", "interfaces": ["eth1"]},
        },
    ],
)
def test_failure_target_shape_is_strict(failure: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FailureScenario.model_validate(
            {
                "name": "invalid",
                "description": "Invalid failure target",
                "failure": failure,
                "expected": {
                    "surviving_planes": ["a"],
                    "probes": [
                        {
                            "plane": "a",
                            "source_node": "gpu01",
                            "destination_node": "gpu03",
                        }
                    ],
                },
            }
        )


def test_schema_rejects_unknown_fields_and_uncovered_planes() -> None:
    with pytest.raises(ValidationError):
        FailureScenario.model_validate(
            {
                "name": "invalid",
                "description": "Invalid expectations",
                "unexpected": True,
                "failure": {
                    "type": "spine-down",
                    "target": {"node": "spine-a1"},
                },
                "expected": {
                    "surviving_planes": ["a", "b"],
                    "probes": [
                        {
                            "plane": "a",
                            "source_node": "gpu01",
                            "destination_node": "gpu03",
                        }
                    ],
                },
            }
        )
