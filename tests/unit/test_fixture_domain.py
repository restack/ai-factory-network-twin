from pathlib import Path

from aftwin.domain.enums import NodeRole
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture


def test_fixture_conversion_matches_golden_domain_shape() -> None:
    fixture = load_fixture(Path("fixtures/mini-dual-plane.yaml"))

    fabric = fixture_to_fabric(fixture)

    assert fabric.name == "mini-dual-plane"
    assert fabric.site == "aif-lab"
    assert len(fabric.nodes) == 12
    assert len(fabric.links) == 16
    assert len(fabric.source_revision) == 64
    assert all("ai-fabric" in node.tags for node in fabric.nodes)
    assert sum(node.role is NodeRole.COMPUTE for node in fabric.nodes) == 4
