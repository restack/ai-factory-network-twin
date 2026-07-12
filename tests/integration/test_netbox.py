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


def test_seed_fetch_and_normalize_are_reproducible(tmp_path: Path) -> None:
    token = os.environ["NETBOX_TOKEN"]
    client = NetBoxClient(os.environ.get("NETBOX_URL", "http://localhost:8000"), SecretStr(token))
    seeder = NetBoxSeeder(client)
    smoke = load_fixture(Path("fixtures/smoke.yaml"))
    mini = load_fixture(Path("fixtures/mini-dual-plane.yaml"))

    seeder.seed(smoke)
    smoke_second = seeder.seed(smoke)
    seeder.seed(mini)
    mini_second = seeder.seed(mini)
    adapter = NetBoxAdapter(client)
    first_snapshot = adapter.fetch_site(mini.site.slug)
    second_snapshot = adapter.fetch_site(mini.site.slug)
    first_hash = adapter.save_snapshot(first_snapshot, tmp_path / "netbox-a.json")
    second_hash = adapter.save_snapshot(second_snapshot, tmp_path / "netbox-b.json")
    fabric = adapter.normalize(first_snapshot)

    assert smoke_second.created == 0
    assert mini_second.created == 0
    assert len(fabric.nodes) == 12
    assert len(fabric.links) == 16
    assert {node.asn for node in fabric.nodes if node.asn is not None} == {
        65001,
        65002,
        65011,
        65012,
        65101,
        65102,
        65111,
        65112,
    }
    assert all("ai-fabric" in node.tags for node in fabric.nodes)
    assert first_hash == second_hash == fabric.source_revision
    assert (tmp_path / "netbox-a.json").read_bytes() == (tmp_path / "netbox-b.json").read_bytes()
    assert token not in (tmp_path / "netbox-a.json").read_text(encoding="utf-8")
