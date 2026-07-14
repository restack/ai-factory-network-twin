"""Collect live Containerlab evidence and compare it with expected state."""

import json
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import ValidationError

from aftwin.backend.contract import NetworkObservedStateCollector, PlatformBackend
from aftwin.backend.registry import get_backend
from aftwin.compiler.expected_state import ExpectedState
from aftwin.compiler.manifest import InventoryMetadata
from aftwin.domain.enums import FabricPlane
from aftwin.errors import RuntimeVerificationError
from aftwin.runtime.executor import CommandExecutionError, CommandResult
from aftwin.runtime.lifecycle import (
    ContainerlabRuntime,
    DeploymentStamp,
    LabLifecycle,
    LabLifecycleError,
)
from aftwin.verify.bgp import ObservedBgpRouter, verify_bgp
from aftwin.verify.reachability import PingOutcome, parse_ping_outcome, verify_reachability
from aftwin.verify.report import VerificationReport, VerificationSection
from aftwin.verify.routes import ObservedRouteTable, verify_routes

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class NodeCommandResult:
    """One command result decoded from Containerlab's JSON wrapper."""

    return_code: int
    stdout: object
    stderr: str


def decode_node_command(result: CommandResult, node: str) -> NodeCommandResult:
    """Decode Containerlab 0.77 exec JSON and retain the inner return code."""
    try:
        payload: object = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeVerificationError(
            f"Containerlab returned invalid exec JSON for {node}",
            details={"node": node, "stderr": result.stderr},
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeVerificationError(
            f"Containerlab returned an unexpected exec result for {node}",
            details={"node": node},
        )
    payload_dict = cast(dict[str, object], payload)
    if len(payload_dict) != 1:
        raise RuntimeVerificationError(
            f"Containerlab returned an unexpected exec result for {node}",
            details={"node": node},
        )
    entries = next(iter(payload_dict.values()))
    if not isinstance(entries, list):
        raise RuntimeVerificationError(
            f"Containerlab returned an unexpected command list for {node}",
            details={"node": node},
        )
    entry_list = cast(list[object], entries)
    if len(entry_list) != 1 or not isinstance(entry_list[0], dict):
        raise RuntimeVerificationError(
            f"Containerlab returned an unexpected command list for {node}",
            details={"node": node},
        )
    entry = cast(dict[str, object], entry_list[0])
    return_code = entry.get("return-code")
    stderr = entry.get("stderr", "")
    if isinstance(return_code, bool) or not isinstance(return_code, int):
        raise RuntimeVerificationError(
            f"Containerlab omitted the inner return code for {node}",
            details={"node": node},
        )
    if not isinstance(stderr, str):
        stderr = str(stderr)
    return NodeCommandResult(
        return_code=return_code,
        stdout=entry.get("stdout", ""),
        stderr=stderr,
    )


class RuntimeVerifier:
    """Collect deterministic BGP, route, and VRF ping evidence."""

    def __init__(
        self,
        containerlab: ContainerlabRuntime,
        *,
        convergence_timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 1.0,
        max_workers: int = 8,
    ) -> None:
        if convergence_timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("verification timeouts must be positive")
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._containerlab = containerlab
        self._convergence_timeout_seconds = convergence_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._max_workers = max_workers

    @staticmethod
    def load_expected(site_dir: Path) -> ExpectedState:
        """Load the generated runtime contract."""
        path = site_dir / "expected-state.json"
        try:
            return ExpectedState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise RuntimeVerificationError(
                f"expected state is unreadable or invalid: {path}",
                details={"path": path.as_posix()},
            ) from error

    def verify(self, site_dir: Path) -> VerificationReport:
        """Collect all live evidence, persist a report, and return it."""
        deployment = self._require_deployed_build(site_dir)
        expected = self.load_expected(site_dir)
        backends = self._node_backends(site_dir)
        topology = site_dir / "topology.clab.yml"
        self._wait_for_readiness(topology, expected, backends)
        bgp = self._wait_for_bgp(topology, expected, backends)
        route_tables = self._wait_for_routes(topology, expected, backends)
        pings = self._collect_pings(topology, expected, backends)
        report = VerificationReport(
            build_hash=deployment.build_hash,
            source_revision=deployment.source_revision,
            sections=(
                verify_bgp(expected.bgp_adjacencies, bgp),
                verify_routes(expected.router_prefixes, expected.isolation, route_tables),
                *verify_reachability(expected.reachability, expected.isolation, pings),
            ),
        )
        report_path = site_dir / "reports" / "runtime-verification.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
        return report

    def verify_connectivity(self, site_dir: Path) -> tuple[VerificationSection, ...]:
        """Verify only endpoint reachability and isolation for a failure scenario."""
        self._require_deployed_build(site_dir)
        expected = self.load_expected(site_dir)
        backends = self._node_backends(site_dir)
        topology = site_dir / "topology.clab.yml"
        pings = self._collect_pings(topology, expected, backends)
        return verify_reachability(expected.reachability, expected.isolation, pings)

    def reachability_contract(self, site_dir: Path) -> frozenset[tuple[FabricPlane, str, str]]:
        """Return directed endpoint probes available to scenario contracts."""
        self._require_deployed_build(site_dir)
        expected = self.load_expected(site_dir)
        return frozenset(
            (probe.plane, probe.source_node, probe.destination_node)
            for probe in expected.reachability
        )

    def _require_deployed_build(self, site_dir: Path) -> DeploymentStamp:
        try:
            return LabLifecycle(self._containerlab).require_deployed_build(site_dir)
        except LabLifecycleError as error:
            raise RuntimeVerificationError(error.message, details=error.details) from error

    @staticmethod
    def _node_backends(site_dir: Path) -> dict[str, PlatformBackend]:
        """Resolve each compiled node's backend from the build inventory."""
        path = site_dir / "inventory.json"
        try:
            inventory = InventoryMetadata.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise RuntimeVerificationError(
                f"compiled inventory is unreadable or invalid: {path}",
                details={"path": path.as_posix()},
            ) from error
        if not inventory.nodes:
            raise RuntimeVerificationError(
                "compiled inventory has no node renderer records; recompile this build",
                details={"path": path.as_posix()},
            )
        backends: dict[str, PlatformBackend] = {}
        for record in inventory.nodes:
            try:
                backends[record.name] = get_backend(record.renderer)
            except ValueError as error:
                raise RuntimeVerificationError(
                    f"compiled inventory names an unknown renderer for {record.name}: {error}",
                    details={"node": record.name, "renderer": record.renderer},
                ) from error
        return backends

    @staticmethod
    def _collector(
        backends: Mapping[str, PlatformBackend], router: str
    ) -> NetworkObservedStateCollector:
        backend = backends.get(router)
        if backend is None:
            raise RuntimeVerificationError(
                f"router is not in the compiled inventory: {router}",
                details={"node": router},
            )
        collector = backend.collector
        if collector is None:
            raise RuntimeVerificationError(
                f"backend {backend.name!r} does not provide observed state for {router}",
                details={"node": router, "renderer": backend.name},
            )
        return collector

    def _exec(self, topology: Path, node: str, command: Sequence[str]) -> NodeCommandResult:
        try:
            result = self._containerlab.exec(topology, node, command)
        except CommandExecutionError as error:
            raise RuntimeVerificationError(
                f"runtime command failed for {node}: {error}",
                details={"node": node, "command": error.as_dict()},
            ) from error
        return decode_node_command(result, node)

    def _parallel(self, function: Callable[[T], R], items: Sequence[T]) -> tuple[R, ...]:
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            return tuple(pool.map(function, items))

    @staticmethod
    def _routers(expected: ExpectedState) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    router.node
                    for adjacency in expected.bgp_adjacencies
                    for router in (adjacency.leaf, adjacency.spine)
                }
            )
        )

    def _wait_for_readiness(
        self,
        topology: Path,
        expected: ExpectedState,
        backends: Mapping[str, PlatformBackend],
    ) -> None:
        """Poll declared backend readiness probes before collecting evidence."""
        pending: dict[str, tuple[str, ...]] = {}
        for router in self._routers(expected):
            readiness = self._collector(backends, router).readiness_command()
            if readiness is not None:
                pending[router] = readiness
        deadline = time.monotonic() + self._convergence_timeout_seconds
        while pending:

            def probe(item: tuple[str, tuple[str, ...]]) -> str | None:
                router, command = item
                try:
                    result = self._exec(topology, router, command)
                except RuntimeVerificationError:
                    return None
                return router if result.return_code == 0 else None

            ready = self._parallel(probe, tuple(sorted(pending.items())))
            for router in ready:
                if router is not None:
                    del pending[router]
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise RuntimeVerificationError(
                    "routers did not accept state queries before the timeout",
                    details={"pending": sorted(pending)},
                )
            time.sleep(self._poll_interval_seconds)

    def _collect_bgp(
        self,
        topology: Path,
        expected: ExpectedState,
        backends: Mapping[str, PlatformBackend],
    ) -> dict[str, ObservedBgpRouter]:
        def collect(router: str) -> ObservedBgpRouter:
            collector = self._collector(backends, router)
            result = self._exec(topology, router, collector.bgp_summary_command())
            if result.return_code != 0:
                raise RuntimeVerificationError(
                    f"BGP command failed inside {router}",
                    details={"node": router, "return_code": result.return_code},
                )
            payload = result.stdout
            if not isinstance(payload, (str, Mapping)):
                raise RuntimeVerificationError(f"BGP output has an invalid shape for {router}")
            try:
                return collector.parse_bgp_summary(router, cast(str | Mapping[str, Any], payload))
            except (ValueError, json.JSONDecodeError) as error:
                raise RuntimeVerificationError(
                    f"BGP output is invalid for {router}: {error}"
                ) from error

        states = self._parallel(collect, self._routers(expected))
        return {state.router: state for state in states}

    def _wait_for_bgp(
        self,
        topology: Path,
        expected: ExpectedState,
        backends: Mapping[str, PlatformBackend],
    ) -> dict[str, ObservedBgpRouter]:
        deadline = time.monotonic() + self._convergence_timeout_seconds
        last_error: RuntimeVerificationError | None = None
        observed: dict[str, ObservedBgpRouter] = {}
        while True:
            try:
                observed = self._collect_bgp(topology, expected, backends)
                last_error = None
                if verify_bgp(expected.bgp_adjacencies, observed).successful:
                    return observed
            except RuntimeVerificationError as error:
                last_error = error
            if time.monotonic() >= deadline:
                if last_error is not None:
                    raise last_error
                return observed
            time.sleep(self._poll_interval_seconds)

    def _collect_routes(
        self,
        topology: Path,
        expected: ExpectedState,
        backends: Mapping[str, PlatformBackend],
    ) -> dict[str, ObservedRouteTable]:
        def collect(router: str) -> ObservedRouteTable:
            collector = self._collector(backends, router)
            result = self._exec(topology, router, collector.route_table_command())
            if result.return_code != 0:
                raise RuntimeVerificationError(
                    f"route command failed inside {router}",
                    details={"node": router, "return_code": result.return_code},
                )
            payload = result.stdout
            if not isinstance(payload, (str, Mapping)):
                raise RuntimeVerificationError(f"route output has an invalid shape for {router}")
            try:
                return collector.parse_route_table(router, cast(str | Mapping[str, Any], payload))
            except (ValueError, json.JSONDecodeError) as error:
                raise RuntimeVerificationError(
                    f"route output is invalid for {router}: {error}"
                ) from error

        tables = self._parallel(collect, self._routers(expected))
        return {table.router: table for table in tables}

    def _wait_for_routes(
        self,
        topology: Path,
        expected: ExpectedState,
        backends: Mapping[str, PlatformBackend],
    ) -> dict[str, ObservedRouteTable]:
        """Wait for expected routes and ECMP paths after BGP is established."""
        deadline = time.monotonic() + self._convergence_timeout_seconds
        last_error: RuntimeVerificationError | None = None
        observed: dict[str, ObservedRouteTable] = {}
        while True:
            try:
                observed = self._collect_routes(topology, expected, backends)
                last_error = None
                if verify_routes(expected.router_prefixes, expected.isolation, observed).successful:
                    return observed
            except RuntimeVerificationError as error:
                last_error = error
            if time.monotonic() >= deadline:
                if last_error is not None:
                    raise last_error
                return observed
            time.sleep(self._poll_interval_seconds)

    def _collect_pings(
        self,
        topology: Path,
        expected: ExpectedState,
        backends: Mapping[str, PlatformBackend],
    ) -> tuple[PingOutcome, ...]:
        jobs: list[tuple[str, str, IPv4Address]] = [
            (probe.source_node, probe.source_vrf, probe.destination_address)
            for probe in expected.reachability
        ]
        jobs.extend(
            (source, contract.source_vrf, destination)
            for contract in expected.isolation
            for source in contract.source_nodes
            for destination in contract.blocked_endpoint_addresses
        )

        def collect(job: tuple[str, str, IPv4Address]) -> PingOutcome:
            node, vrf, destination = job
            backend = backends.get(node)
            command = None if backend is None else backend.ping_command(vrf, str(destination))
            if command is None:
                raise RuntimeVerificationError(
                    f"no backend reachability probe is available for {node}",
                    details={"node": node},
                )
            result = self._exec(topology, node, command)
            stdout = result.stdout if isinstance(result.stdout, str) else json.dumps(result.stdout)
            return parse_ping_outcome(
                source_node=node,
                source_vrf=vrf,
                destination_address=destination,
                return_code=result.return_code,
                stdout=stdout,
                stderr=result.stderr,
            )

        return self._parallel(collect, tuple(jobs))
