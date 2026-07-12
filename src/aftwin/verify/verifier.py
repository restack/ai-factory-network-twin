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

from aftwin.compiler.expected_state import ExpectedState
from aftwin.errors import RuntimeVerificationError
from aftwin.runtime.executor import CommandExecutionError, CommandResult
from aftwin.runtime.lifecycle import ContainerlabRuntime
from aftwin.verify.bgp import ObservedBgpRouter, parse_bgp_summary, verify_bgp
from aftwin.verify.reachability import PingOutcome, parse_ping_outcome, verify_reachability
from aftwin.verify.report import VerificationReport
from aftwin.verify.routes import ObservedRouteTable, parse_route_table, verify_routes

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
        expected = self.load_expected(site_dir)
        topology = site_dir / "topology.clab.yml"
        bgp = self._wait_for_bgp(topology, expected)
        route_tables = self._wait_for_routes(topology, expected)
        pings = self._collect_pings(topology, expected)
        report = VerificationReport(
            sections=(
                verify_bgp(expected.bgp_adjacencies, bgp),
                verify_routes(expected.router_prefixes, expected.isolation, route_tables),
                *verify_reachability(expected.reachability, expected.isolation, pings),
            )
        )
        report_path = site_dir / "reports" / "runtime-verification.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
        return report

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

    def _collect_bgp(self, topology: Path, expected: ExpectedState) -> dict[str, ObservedBgpRouter]:
        def collect(router: str) -> ObservedBgpRouter:
            result = self._exec(topology, router, ("vtysh", "-c", "show bgp summary json"))
            if result.return_code != 0:
                raise RuntimeVerificationError(
                    f"BGP command failed inside {router}",
                    details={"node": router, "return_code": result.return_code},
                )
            payload = result.stdout
            if not isinstance(payload, (str, Mapping)):
                raise RuntimeVerificationError(f"BGP output has an invalid shape for {router}")
            try:
                return parse_bgp_summary(router, cast(str | Mapping[str, Any], payload))
            except (ValueError, json.JSONDecodeError) as error:
                raise RuntimeVerificationError(
                    f"BGP output is invalid for {router}: {error}"
                ) from error

        states = self._parallel(collect, self._routers(expected))
        return {state.router: state for state in states}

    def _wait_for_bgp(
        self, topology: Path, expected: ExpectedState
    ) -> dict[str, ObservedBgpRouter]:
        deadline = time.monotonic() + self._convergence_timeout_seconds
        last_error: RuntimeVerificationError | None = None
        observed: dict[str, ObservedBgpRouter] = {}
        while True:
            try:
                observed = self._collect_bgp(topology, expected)
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
        self, topology: Path, expected: ExpectedState
    ) -> dict[str, ObservedRouteTable]:
        def collect(router: str) -> ObservedRouteTable:
            result = self._exec(topology, router, ("vtysh", "-c", "show ip route json"))
            if result.return_code != 0:
                raise RuntimeVerificationError(
                    f"route command failed inside {router}",
                    details={"node": router, "return_code": result.return_code},
                )
            payload = result.stdout
            if not isinstance(payload, (str, Mapping)):
                raise RuntimeVerificationError(f"route output has an invalid shape for {router}")
            try:
                return parse_route_table(router, cast(str | Mapping[str, Any], payload))
            except (ValueError, json.JSONDecodeError) as error:
                raise RuntimeVerificationError(
                    f"route output is invalid for {router}: {error}"
                ) from error

        tables = self._parallel(collect, self._routers(expected))
        return {table.router: table for table in tables}

    def _wait_for_routes(
        self, topology: Path, expected: ExpectedState
    ) -> dict[str, ObservedRouteTable]:
        """Wait for expected routes and ECMP paths after BGP is established."""
        deadline = time.monotonic() + self._convergence_timeout_seconds
        last_error: RuntimeVerificationError | None = None
        observed: dict[str, ObservedRouteTable] = {}
        while True:
            try:
                observed = self._collect_routes(topology, expected)
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

    def _collect_pings(self, topology: Path, expected: ExpectedState) -> tuple[PingOutcome, ...]:
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
            result = self._exec(
                topology,
                node,
                ("ip", "vrf", "exec", vrf, "ping", "-c", "1", "-W", "1", str(destination)),
            )
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
