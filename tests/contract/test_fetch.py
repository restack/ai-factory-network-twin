from aftwin.netbox.adapter import NetBoxAdapter


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.responses: dict[str, list[dict[str, object]]] = {
            "dcim.devices": [
                {
                    "id": 10,
                    "name": "spine-a1",
                    "role": 20,
                    "platform": 30,
                    "tags": [40],
                    "custom_fields": {"bgp_asn": 50, "fabric_plane": "a"},
                }
            ],
            "dcim.interfaces": [
                {
                    "id": 60,
                    "name": "lo",
                    "device": 10,
                    "custom_fields": {"fabric_plane": "a", "fabric_role": "loopback"},
                }
            ],
            "ipam.ip_addresses": [{"id": 70, "address": "10.255.0.1/32"}],
            "dcim.cables": [],
            "ipam.asns": [{"id": 50, "asn": 65001}, {"id": 999, "asn": 65535}],
            "dcim.device_roles": [
                {"id": 20, "slug": "fabric-spine"},
                {"id": 999, "slug": "unrelated"},
            ],
            "dcim.platforms": [
                {"id": 30, "slug": "frr"},
                {"id": 999, "slug": "unrelated"},
            ],
            "extras.tags": [
                {"id": 40, "slug": "ai-fabric"},
                {"id": 999, "slug": "unrelated"},
            ],
        }

    def one(self, path: str, **filters: object) -> dict[str, object] | None:
        self.calls.append((path, filters))
        return {"id": 1, "name": "Lab", "slug": "aif-lab"}

    def list(self, path: str, **filters: object) -> list[dict[str, object]]:
        self.calls.append((path, filters))
        return [dict(record) for record in self.responses[path]]


def test_fetch_site_scopes_relations_and_attaches_addresses() -> None:
    client = FakeClient()
    adapter = NetBoxAdapter(client)

    snapshot = adapter.fetch_site("aif-lab")

    assert snapshot["asns"] == [{"id": 50, "asn": 65001}]
    assert snapshot["device_roles"] == [{"id": 20, "slug": "fabric-spine"}]
    assert snapshot["platforms"] == [{"id": 30, "slug": "frr"}]
    assert snapshot["tags"] == [{"id": 40, "slug": "ai-fabric"}]
    interfaces = snapshot["interfaces"]
    assert isinstance(interfaces, list)
    assert interfaces[0]["_addresses"] == [{"id": 70, "address": "10.255.0.1/32"}]
    assert ("dcim.devices", {"site_id": 1}) in client.calls
    assert ("dcim.interfaces", {"device_id": 10}) in client.calls
    assert ("ipam.ip_addresses", {"interface_id": 60}) in client.calls
