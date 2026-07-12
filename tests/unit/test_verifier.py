import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from aftwin.compiler.expected_state import ExpectedState
from aftwin.errors import RuntimeVerificationError
from aftwin.runtime.executor import CommandResult
from aftwin.verify.verifier import RuntimeVerifier, decode_node_command

GOLDEN = Path("tests/golden/mini-dual-plane")


class PassingRuntime:
    def __init__(self, expected: ExpectedState) -> None:
        self.expected = expected

    def exec(self, topology: Path, node: str, command: Sequence[str]) -> CommandResult:
        del topology
        if tuple(command) == ("vtysh", "-c", "show bgp summary json"):
            peers: dict[str, dict[str, object]] = {}
            local_asn = 0
            for adjacency in self.expected.bgp_adjacencies:
                for local, remote in (
                    (adjacency.leaf, adjacency.spine),
                    (adjacency.spine, adjacency.leaf),
                ):
                    if local.node == node:
                        local_asn = local.asn
                        peers[str(remote.address)] = {
                            "remoteAs": remote.asn,
                            "state": "Established",
                        }
            inner_stdout: object = {"ipv4Unicast": {"as": local_asn, "peers": peers}}
            return_code = 0
        elif tuple(command) == ("vtysh", "-c", "show ip route json"):
            routes: dict[str, list[dict[str, object]]] = {}
            for expectation in self.expected.router_prefixes:
                if expectation.router != node:
                    continue
                next_hops = [
                    {"ip": f"192.0.2.{index + 1}", "active": True}
                    for index in range(expectation.min_next_hops)
                ]
                routes[str(expectation.prefix)] = [
                    {
                        "protocol": expectation.protocol,
                        "selected": True,
                        "installed": True,
                        "nexthops": next_hops,
                    }
                ]
            inner_stdout = routes
            return_code = 0
        else:
            vrf = command[3]
            destination = command[-1]
            same_plane = (vrf == "fabric-a" and destination.startswith("10.0.")) or (
                vrf == "fabric-b" and destination.startswith("10.1.")
            )
            inner_stdout = "ping evidence"
            return_code = 0 if same_plane else 1
        wrapper = {
            f"clab-mini-dual-plane-{node}": [
                {
                    "cmd": list(command),
                    "return-code": return_code,
                    "stdout": inner_stdout,
                    "stderr": "",
                }
            ]
        }
        return CommandResult(("containerlab", "exec"), 0, json.dumps(wrapper), "", 0.01)

    def deploy(self, topology: Path, *, reconfigure: bool = False) -> CommandResult:
        raise AssertionError((topology, reconfigure))

    def destroy(self, topology: Path, *, cleanup: bool = True) -> CommandResult:
        raise AssertionError((topology, cleanup))

    def inspect(self, topology: Path) -> CommandResult:
        raise AssertionError(topology)

    def inspect_all(self) -> CommandResult:
        raise AssertionError("not used by verifier")


def test_runtime_verifier_collects_complete_passing_matrix(tmp_path: Path) -> None:
    expected = ExpectedState.model_validate_json((GOLDEN / "expected-state.json").read_text())
    (tmp_path / "expected-state.json").write_text(
        (GOLDEN / "expected-state.json").read_text(), encoding="utf-8"
    )
    (tmp_path / "topology.clab.yml").write_text("name: mini-dual-plane\n", encoding="utf-8")

    report = RuntimeVerifier(PassingRuntime(expected), max_workers=4).verify(tmp_path)

    assert report.passed
    assert {section.name: (section.passed, section.expected) for section in report.sections} == {
        "bgp-sessions": (8, 8),
        "cross-plane-isolation": (32, 32),
        "reachability-plane-a": (12, 12),
        "reachability-plane-b": (12, 12),
        "routes": (32, 32),
    }
    assert (tmp_path / "reports" / "runtime-verification.json").read_text() == report.to_json()


def test_decode_node_command_requires_inner_return_code() -> None:
    result = CommandResult(
        ("containerlab", "exec"),
        0,
        json.dumps({"clab-mini-gpu01": [{"stdout": "missing"}]}),
        "",
        0.01,
    )

    with pytest.raises(RuntimeVerificationError, match="inner return code"):
        decode_node_command(result, "gpu01")
