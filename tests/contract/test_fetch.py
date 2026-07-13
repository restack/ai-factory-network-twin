from typing import cast

from aftwin.netbox.adapter import NetBoxAdapter


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.responses: dict[str, list[dict[str, object]]] = {
            "dcim.devices": [
                {
                    "id": 10,
                    "name": "spine-a1",
                    "role": {"id": 20, "slug": "fabric-spine", "url": "secret-role-url"},
                    "platform": {"id": 30, "slug": "frr", "display": "FRR"},
                    "tags": [{"id": 40, "slug": "ai-fabric", "url": "secret-tag-url"}],
                    "custom_fields": {
                        "bgp_asn": {"id": 50, "display": "AS65001"},
                        "fabric_plane": {"value": "a", "label": "Plane A"},
                        "api_password": "must-not-be-snapshotted",
                    },
                    "comments": "must-not-be-snapshotted",
                    "url": "secret-device-url",
                    "created": "2026-01-01T00:00:00Z",
                }
            ],
            "dcim.interfaces": [
                {
                    "id": 60,
                    "name": "lo",
                    "device": {"id": 10, "name": "spine-a1", "url": "secret-device-url"},
                    "custom_fields": {
                        "fabric_plane": {"value": "a", "label": "Plane A"},
                        "fabric_role": {"value": "loopback", "label": "Loopback"},
                        "credentials": "must-not-be-snapshotted",
                    },
                    "description": "must-not-be-snapshotted",
                    "url": "secret-interface-url",
                }
            ],
            "ipam.ip_addresses": [
                {
                    "id": 70,
                    "address": "10.255.0.1/32",
                    "comments": "must-not-be-snapshotted",
                    "url": "secret-address-url",
                }
            ],
            "dcim.cables": [
                {
                    "id": 80,
                    "a_terminations": [
                        {
                            "object_id": 60,
                            "object_type": "dcim.interface",
                            "object": {"url": "secret-termination-url"},
                        }
                    ],
                    "b_terminations": [{"id": 61, "url": "secret-termination-url"}],
                    "comments": "must-not-be-snapshotted",
                    "url": "secret-cable-url",
                }
            ],
            "ipam.asns": [
                {"id": 50, "asn": 65001, "comments": "must-not-be-snapshotted"},
                {"id": 999, "asn": 65535},
            ],
            "dcim.device_roles": [
                {"id": 20, "slug": "fabric-spine", "description": "drop me"},
                {"id": 999, "slug": "unrelated"},
            ],
            "dcim.platforms": [
                {"id": 30, "slug": "frr", "url": "secret-platform-url"},
                {"id": 999, "slug": "unrelated"},
            ],
            "extras.tags": [
                {"id": 40, "slug": "ai-fabric", "description": "drop me"},
                {"id": 999, "slug": "unrelated"},
            ],
        }

    def one(self, path: str, **filters: object) -> dict[str, object] | None:
        self.calls.append((path, filters))
        return {
            "id": 1,
            "name": "Lab",
            "slug": "aif-lab",
            "comments": "must-not-be-snapshotted",
            "url": "secret-site-url",
            "last_updated": "2026-01-01T00:00:00Z",
        }

    def list(self, path: str, **filters: object) -> list[dict[str, object]]:
        self.calls.append((path, filters))
        return [dict(record) for record in self.responses[path]]


def test_fetch_site_scopes_relations_and_attaches_addresses() -> None:
    client = FakeClient()
    adapter = NetBoxAdapter(client)

    snapshot = adapter.fetch_site("aif-lab")

    assert snapshot["site"] == {"id": 1, "slug": "aif-lab"}
    assert snapshot["devices"] == [
        {
            "id": 10,
            "name": "spine-a1",
            "role": {"id": 20, "slug": "fabric-spine"},
            "platform": {"id": 30, "slug": "frr"},
            "tags": [{"id": 40, "slug": "ai-fabric"}],
            "custom_fields": {
                "fabric_plane": {"value": "a"},
                "bgp_asn": {"id": 50},
            },
        }
    ]
    assert snapshot["asns"] == [{"id": 50, "asn": 65001}]
    assert snapshot["device_roles"] == [{"id": 20, "slug": "fabric-spine"}]
    assert snapshot["platforms"] == [{"id": 30, "slug": "frr"}]
    assert snapshot["tags"] == [{"id": 40, "slug": "ai-fabric"}]
    assert snapshot["cables"] == [
        {
            "id": 80,
            "a_terminations": [{"object_id": 60}],
            "b_terminations": [{"id": 61}],
        }
    ]
    interfaces = snapshot["interfaces"]
    assert isinstance(interfaces, list)
    assert interfaces == [
        {
            "id": 60,
            "name": "lo",
            "device": {"id": 10},
            "custom_fields": {
                "fabric_plane": {"value": "a"},
                "fabric_role": {"value": "loopback"},
            },
            "_addresses": [{"id": 70, "address": "10.255.0.1/32"}],
        }
    ]
    assert ("dcim.devices", {"site_id": 1}) in client.calls
    assert ("dcim.interfaces", {"device_id": 10}) in client.calls
    assert ("ipam.ip_addresses", {"interface_id": 60}) in client.calls


def test_fetch_site_preserves_scalar_relationship_shape() -> None:
    client = FakeClient()
    device = client.responses["dcim.devices"][0]
    device["role"] = 20
    device["platform"] = 30
    device["tags"] = [40]
    device["custom_fields"] = {"bgp_asn": 50, "fabric_plane": "a"}
    interface = client.responses["dcim.interfaces"][0]
    interface["device"] = 10
    interface["custom_fields"] = {"fabric_plane": "a", "fabric_role": "loopback"}

    snapshot = NetBoxAdapter(client).fetch_site("aif-lab")

    devices = snapshot["devices"]
    assert isinstance(devices, list)
    sanitized_device = cast(dict[str, object], devices[0])
    assert sanitized_device["role"] == 20
    assert sanitized_device["platform"] == 30
    assert sanitized_device["tags"] == [40]
    assert sanitized_device["custom_fields"] == {"fabric_plane": "a", "bgp_asn": 50}
    interfaces = snapshot["interfaces"]
    assert isinstance(interfaces, list)
    sanitized_interface = cast(dict[str, object], interfaces[0])
    assert sanitized_interface["device"] == 10
    assert sanitized_interface["custom_fields"] == {
        "fabric_plane": "a",
        "fabric_role": "loopback",
    }


def test_fetch_site_can_narrow_devices_by_tag() -> None:
    client = FakeClient()

    NetBoxAdapter(client).fetch_site("aif-lab", tag_slug="ai-fabric")

    assert ("dcim.devices", {"site_id": 1, "tag": "ai-fabric"}) in client.calls
