from collections import defaultdict
from ipaddress import IPv4Network
from pathlib import Path

from aftwin.domain.enums import FabricPlane, InterfaceRole, LinkKind, NodeRole
from aftwin.netbox.fixture import DeviceFixture, InterfaceFixture, load_fixture

FIXTURE_PATH = Path("fixtures/mini-dual-plane.yaml")
NETWORK_ROLES = {NodeRole.SPINE, NodeRole.LEAF}
FABRIC_PLANES = (FabricPlane.A, FabricPlane.B)


def _devices_by_name() -> dict[str, DeviceFixture]:
    fixture = load_fixture(FIXTURE_PATH)
    return {device.name: device for device in fixture.devices}


def _interfaces_by_endpoint() -> dict[tuple[str, str], InterfaceFixture]:
    fixture = load_fixture(FIXTURE_PATH)
    return {
        (device.name, interface.name): interface
        for device in fixture.devices
        for interface in device.interfaces
    }


def test_mini_dual_plane_has_exact_inventory_and_link_counts() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    network_devices = [device for device in fixture.devices if device.role in NETWORK_ROLES]
    compute_devices = [device for device in fixture.devices if device.role is NodeRole.COMPUTE]

    assert fixture.name == "mini-dual-plane"
    assert len(fixture.devices) == 12
    assert len(network_devices) == 8
    assert len(compute_devices) == 4
    assert len(fixture.links) == 16
    assert sum(link.kind is LinkKind.FABRIC for link in fixture.links) == 8
    assert sum(link.kind is LinkKind.HOST for link in fixture.links) == 8


def test_mini_dual_plane_assigns_devices_and_links_to_expected_planes() -> None:
    fixture = load_fixture(FIXTURE_PATH)

    for plane in FABRIC_PLANES:
        assert (
            sum(
                device.role is NodeRole.SPINE and device.plane is plane
                for device in fixture.devices
            )
            == 2
        )
        assert (
            sum(
                device.role is NodeRole.LEAF and device.plane is plane for device in fixture.devices
            )
            == 2
        )
        assert sum(link.plane is plane for link in fixture.links) == 8

    computes = [device for device in fixture.devices if device.role is NodeRole.COMPUTE]
    assert all(device.plane is FabricPlane.SHARED for device in computes)


def test_mini_dual_plane_has_unique_network_asns_and_32_loopbacks() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    network_devices = [device for device in fixture.devices if device.role in NETWORK_ROLES]

    asns = [device.asn for device in network_devices]
    assert all(asn is not None for asn in asns)
    assert len(set(asns)) == len(network_devices)

    for device in network_devices:
        loopbacks = [
            interface for interface in device.interfaces if interface.role is InterfaceRole.LOOPBACK
        ]
        assert len(loopbacks) == 1, device.name
        assert len(loopbacks[0].addresses) == 1, device.name
        assert loopbacks[0].addresses[0].network.prefixlen == 32, device.name


def test_every_link_uses_one_shared_31_endpoint_network() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    interfaces = _interfaces_by_endpoint()

    for link in fixture.links:
        a_interface = interfaces[(link.a.device, link.a.interface)]
        b_interface = interfaces[(link.b.device, link.b.interface)]

        assert len(a_interface.addresses) == 1, link
        assert len(b_interface.addresses) == 1, link
        a_address = a_interface.addresses[0]
        b_address = b_interface.addresses[0]
        assert a_address.network.prefixlen == 31, link
        assert b_address.network.prefixlen == 31, link
        assert a_address.network == b_address.network, link
        assert a_address.ip != b_address.ip, link


def test_every_leaf_connects_to_both_spines_in_its_plane() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    devices = _devices_by_name()
    fabric_neighbors: dict[str, set[str]] = defaultdict(set)

    for link in fixture.links:
        if link.kind is LinkKind.FABRIC:
            fabric_neighbors[link.a.device].add(link.b.device)
            fabric_neighbors[link.b.device].add(link.a.device)

    for leaf in (device for device in fixture.devices if device.role is NodeRole.LEAF):
        expected_spines = {
            device.name
            for device in fixture.devices
            if device.role is NodeRole.SPINE and device.plane is leaf.plane
        }
        assert fabric_neighbors[leaf.name] == expected_spines
        assert all(devices[name].plane is leaf.plane for name in expected_spines)


def test_every_compute_has_exactly_one_host_interface_and_link_per_plane() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    devices = _devices_by_name()
    interfaces = _interfaces_by_endpoint()

    host_links_by_compute_plane: dict[tuple[str, FabricPlane], int] = defaultdict(int)
    for link in fixture.links:
        if link.kind is not LinkKind.HOST:
            continue
        endpoint_devices = (devices[link.a.device], devices[link.b.device])
        compute_endpoints = [
            device for device in endpoint_devices if device.role is NodeRole.COMPUTE
        ]
        leaf_endpoints = [device for device in endpoint_devices if device.role is NodeRole.LEAF]
        assert len(compute_endpoints) == 1, link
        assert len(leaf_endpoints) == 1, link
        assert leaf_endpoints[0].plane is link.plane, link

        compute = compute_endpoints[0]
        compute_endpoint = link.a if link.a.device == compute.name else link.b
        compute_interface = interfaces[(compute_endpoint.device, compute_endpoint.interface)]
        assert compute_interface.role is InterfaceRole.HOST, link
        assert compute_interface.plane is link.plane, link
        host_links_by_compute_plane[(compute.name, link.plane)] += 1

    computes = [device for device in fixture.devices if device.role is NodeRole.COMPUTE]
    for compute in computes:
        for plane in FABRIC_PLANES:
            host_interfaces = [
                interface
                for interface in compute.interfaces
                if interface.role is InterfaceRole.HOST and interface.plane is plane
            ]
            assert len(host_interfaces) == 1, (compute.name, plane)
            assert host_links_by_compute_plane[(compute.name, plane)] == 1


def test_planes_have_no_cross_plane_links_or_address_pool_overlap() -> None:
    fixture = load_fixture(FIXTURE_PATH)
    devices = _devices_by_name()
    interfaces = _interfaces_by_endpoint()
    networks_by_plane: dict[FabricPlane, set[IPv4Network]] = defaultdict(set)

    for link in fixture.links:
        for endpoint in (link.a, link.b):
            device = devices[endpoint.device]
            interface = interfaces[(endpoint.device, endpoint.interface)]
            assert interface.plane is link.plane, link
            if device.role in NETWORK_ROLES:
                assert device.plane is link.plane, link

    for device in fixture.devices:
        for interface in device.interfaces:
            if interface.plane in FABRIC_PLANES:
                networks_by_plane[interface.plane].update(
                    address.network for address in interface.addresses
                )

    assert networks_by_plane[FabricPlane.A]
    assert networks_by_plane[FabricPlane.B]
    for plane_a_network in networks_by_plane[FabricPlane.A]:
        assert all(
            not plane_a_network.overlaps(plane_b_network)
            for plane_b_network in networks_by_plane[FabricPlane.B]
        ), plane_a_network
