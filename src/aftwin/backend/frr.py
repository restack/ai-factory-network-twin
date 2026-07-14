"""FRR platform backend."""

from collections.abc import Mapping
from typing import Any, ClassVar

from aftwin.backend.capabilities import BackendCapability
from aftwin.backend.contract import (
    BackendRoleClass,
    GeneratedFile,
    NetworkObservedStateCollector,
    PlatformBackend,
)
from aftwin.compiler.expected_state import ExpectedState
from aftwin.domain.models import Fabric, Node
from aftwin.render.frr import DAEMONS, render_frr_config
from aftwin.verify.bgp import ObservedBgpRouter, parse_bgp_summary
from aftwin.verify.routes import ObservedRouteTable, parse_route_table


class FrrObservedStateCollector(NetworkObservedStateCollector):
    """Collect FRR evidence through vtysh JSON commands."""

    def bgp_summary_command(self) -> tuple[str, ...]:
        return ("vtysh", "-c", "show bgp summary json")

    def parse_bgp_summary(self, router: str, payload: str | Mapping[str, Any]) -> ObservedBgpRouter:
        return parse_bgp_summary(router, payload)

    def route_table_command(self) -> tuple[str, ...]:
        return ("vtysh", "-c", "show ip route json")

    def parse_route_table(
        self, router: str, payload: str | Mapping[str, Any]
    ) -> ObservedRouteTable:
        return parse_route_table(router, payload)


class FrrBackend(PlatformBackend):
    """Render FRR routers as plain Linux containers with bind-mounted config."""

    name: ClassVar[str] = "frr"
    role_class: ClassVar[BackendRoleClass] = BackendRoleClass.NETWORK
    capabilities: ClassVar[frozenset[BackendCapability]] = frozenset(
        {
            BackendCapability.BGP_IPV4_UNICAST,
            BackendCapability.ECMP_MULTIPATH,
            BackendCapability.BGP_OBSERVED_STATE,
            BackendCapability.ROUTE_OBSERVED_STATE,
        }
    )

    def render_node(
        self, fabric: Fabric, node: Node, expected: ExpectedState
    ) -> tuple[GeneratedFile, ...]:
        base = f"configs/routers/{node.name}"
        return (
            GeneratedFile(path=f"{base}/daemons", content=DAEMONS),
            GeneratedFile(path=f"{base}/frr.conf", content=render_frr_config(fabric, node)),
        )

    def containerlab_node(
        self, node: Node, *, kind: str, image: str, group: str, node_type: str | None = None
    ) -> dict[str, Any]:
        if node_type is not None:
            raise ValueError(f"the {self.name!r} backend does not support a node type override")
        return {
            "kind": kind,
            "image": image,
            "group": group,
            "binds": [
                f"configs/routers/{node.name}/daemons:/etc/frr/daemons:ro",
                f"configs/routers/{node.name}/frr.conf:/etc/frr/frr.conf:ro",
            ],
            "sysctls": {
                "net.ipv4.ip_forward": 1,
                "net.ipv4.conf.all.rp_filter": 0,
                "net.ipv4.conf.default.rp_filter": 0,
            },
        }

    @property
    def collector(self) -> NetworkObservedStateCollector:
        return _COLLECTOR


_COLLECTOR = FrrObservedStateCollector()
