import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from aftwin.netbox.adapter import NetBoxAdapter
from aftwin.netbox.client import NetBoxClient
from aftwin.netbox.fixture import load_fixture
from aftwin.netbox.seeder import NetBoxSeeder

pytestmark = [
    pytest.mark.netbox,
    pytest.mark.skipif(
        os.getenv("AFTWIN_RUN_NETBOX_INTEGRATION") != "1",
        reason="local NetBox integration test is disabled",
    ),
]


def test_seed_fetch_and_normalize_are_reproducible() -> None:
    token = os.environ["NETBOX_TOKEN"]
    client = NetBoxClient(os.environ.get("NETBOX_URL", "http://localhost:8000"), SecretStr(token))
    fixture = load_fixture(Path("fixtures/smoke.yaml"))
    seeder = NetBoxSeeder(client)

    seeder.seed(fixture)
    second = seeder.seed(fixture)
    fabric = NetBoxAdapter(client).normalize(NetBoxAdapter(client).fetch_site(fixture.site.slug))

    assert second.created == 0
    assert len(fabric.nodes) == 3
    assert len(fabric.links) == 2
    assert {node.asn for node in fabric.nodes} == {None, 65001, 65101}
