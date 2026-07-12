from aftwin.domain.enums import InterfaceRole, LinkKind, NodeRole
from aftwin.netbox.adapter import NetBoxAdapter


def test_normalize_stored_netbox_shape() -> None:
    snapshot: dict[str, object] = {
        "site": {"id": 1, "name": "Lab", "slug": "lab"},
        "devices": [
            {
                "id": 10,
                "name": "spine-a1",
                "role": {"slug": "fabric-spine"},
                "platform": {"slug": "frr"},
                "custom_fields": {"fabric_plane": {"value": "a"}, "bgp_asn": {"id": 50}},
            },
            {
                "id": 11,
                "name": "leaf-a1",
                "role": {"slug": "fabric-leaf"},
                "platform": {"slug": "frr"},
                "custom_fields": {"fabric_plane": {"value": "a"}, "bgp_asn": {"id": 51}},
            },
        ],
        "interfaces": [
            {
                "id": 100,
                "name": "lo",
                "device": {"id": 10},
                "custom_fields": {
                    "fabric_plane": {"value": "a"},
                    "fabric_role": {"value": "loopback"},
                },
                "_addresses": [{"id": 1000, "address": "10.255.0.1/32"}],
            },
            {
                "id": 101,
                "name": "eth1",
                "device": {"id": 10},
                "custom_fields": {
                    "fabric_plane": {"value": "a"},
                    "fabric_role": {"value": "downlink"},
                },
                "_addresses": [{"id": 1001, "address": "10.0.0.0/31"}],
            },
            {
                "id": 102,
                "name": "eth1",
                "device": {"id": 11},
                "custom_fields": {
                    "fabric_plane": {"value": "a"},
                    "fabric_role": {"value": "uplink"},
                },
                "_addresses": [{"id": 1002, "address": "10.0.0.1/31"}],
            },
        ],
        "cables": [
            {
                "id": 200,
                "a_terminations": [{"object_id": 101}],
                "b_terminations": [{"object_id": 102}],
            }
        ],
        "asns": [{"id": 50, "asn": 65001}, {"id": 51, "asn": 65101}],
    }

    fabric = NetBoxAdapter.normalize(snapshot)

    assert fabric.site == "lab"
    assert fabric.nodes[0].role is NodeRole.LEAF
    assert fabric.nodes[1].asn == 65001
    assert fabric.nodes[1].loopback is not None
    assert fabric.nodes[1].interfaces[0].role is InterfaceRole.DOWNLINK
    assert fabric.links[0].kind is LinkKind.FABRIC
