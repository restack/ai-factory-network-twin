from pathlib import Path

import pytest
from pydantic import ValidationError

from aftwin.netbox.fixture import NetBoxFixture, load_fixture


def test_smoke_fixture_is_valid() -> None:
    fixture = load_fixture(Path("fixtures/smoke.yaml"))

    assert fixture.name == "smoke"
    assert fixture.site.slug == "aif-lab"
    assert len(fixture.devices) == 3
    assert len(fixture.links) == 2


def test_fixture_rejects_unknown_link_endpoint() -> None:
    with pytest.raises(ValidationError, match="unknown interface"):
        NetBoxFixture.model_validate(
            {
                "schema_version": 1,
                "name": "invalid",
                "site": {"name": "Lab", "slug": "lab"},
                "tags": [],
                "devices": [],
                "links": [
                    {
                        "a": {"device": "missing", "interface": "eth1"},
                        "b": {"device": "missing", "interface": "eth2"},
                        "plane": "a",
                        "kind": "fabric",
                    }
                ],
            }
        )
