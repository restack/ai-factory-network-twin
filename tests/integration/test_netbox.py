import json
import os
from pathlib import Path

import pytest
from pydantic import SecretStr

from aftwin.cli import main
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


def test_seed_fetch_and_normalize_are_reproducible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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

    monkeypatch.setenv("AFTWIN_BUILD_DIR", str(tmp_path / "build"))
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "validate",
                "--site",
                "aif-lab",
                "--profile",
                "config/policies/mini-dual-plane.yaml",
            ]
        )
    assert raised.value.code == 0
    assert "Static validation: PASS" in capsys.readouterr().out
    assert (tmp_path / "build/aif-lab/source/netbox.json").is_file()
    assert (tmp_path / "build/aif-lab/reports/static-validation.json").is_file()
    human_report_bytes = (tmp_path / "build/aif-lab/reports/static-validation.json").read_bytes()

    with pytest.raises(SystemExit) as json_exit:
        main(
            [
                "validate",
                "--site",
                "aif-lab",
                "--profile",
                "config/policies/mini-dual-plane.yaml",
                "--output",
                "json",
            ]
        )
    assert json_exit.value.code == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert (
        tmp_path / "build/aif-lab/reports/static-validation.json"
    ).read_bytes() == human_report_bytes

    invalid_profile = tmp_path / "overlapping-pools.yaml"
    invalid_profile.write_text(
        """name: overlapping-pools
required_planes: [a, b]
supported_network_platforms: [frr]
required_tag: ai-fabric
fabric_p2p_prefix_length: 31
host_p2p_prefix_length: 31
spine_count_by_plane: {a: 2, b: 2}
plane_address_pools:
  a: [10.0.0.0/16, 10.255.0.0/24]
  b: [10.0.0.0/16, 10.1.0.0/16, 10.255.1.0/24]
""",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(SystemExit) as invalid_exit:
        main(
            [
                "validate",
                "--site",
                "aif-lab",
                "--profile",
                str(invalid_profile),
                "--output",
                "json",
            ]
        )
    invalid_report = json.loads(capsys.readouterr().out)
    assert invalid_exit.value.code == 2
    assert invalid_report["passed"] is False
    assert "ADR005" in {finding["rule_id"] for finding in invalid_report["findings"]}
