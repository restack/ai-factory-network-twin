"""Linux VRF endpoint platform backend."""

from typing import Any, ClassVar

from aftwin.backend.capabilities import BackendCapability
from aftwin.backend.contract import BackendRoleClass, GeneratedFile, PlatformBackend
from aftwin.compiler.expected_state import ExpectedState
from aftwin.domain.models import Fabric, Node
from aftwin.render.endpoint import render_endpoint_setup


class LinuxEndpointBackend(PlatformBackend):
    """Render compute and storage endpoints as Linux containers with VRFs."""

    name: ClassVar[str] = "linux_endpoint"
    role_class: ClassVar[BackendRoleClass] = BackendRoleClass.ENDPOINT
    capabilities: ClassVar[frozenset[BackendCapability]] = frozenset(
        {
            BackendCapability.VRF_ENDPOINT,
            BackendCapability.PING_PROBE,
        }
    )

    def render_node(
        self, fabric: Fabric, node: Node, expected: ExpectedState
    ) -> tuple[GeneratedFile, ...]:
        return (
            GeneratedFile(
                path=f"configs/endpoints/{node.name}/setup.sh",
                content=render_endpoint_setup(node, expected.endpoint_prefixes),
                executable=True,
            ),
        )

    def containerlab_node(self, node: Node, *, kind: str, image: str, group: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "image": image,
            "group": group,
            "binds": [
                f"configs/endpoints/{node.name}/setup.sh:/usr/local/sbin/aftwin-endpoint-setup:ro"
            ],
            "exec": ["/bin/sh /usr/local/sbin/aftwin-endpoint-setup"],
            "sysctls": {
                "net.ipv4.ip_forward": 0,
                "net.ipv4.conf.all.rp_filter": 0,
                "net.ipv4.conf.default.rp_filter": 0,
            },
        }

    def ping_command(self, vrf: str, destination: str) -> tuple[str, ...]:
        return ("ip", "vrf", "exec", vrf, "ping", "-c", "1", "-W", "1", destination)
