from collections.abc import Sequence
from pathlib import Path

import pytest

from aftwin.runtime.containerlab import Containerlab
from aftwin.runtime.executor import CommandResult


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], float | None]] = []

    def run(self, argv: Sequence[str], *, timeout_seconds: float | None = None) -> CommandResult:
        command = tuple(argv)
        self.calls.append((command, timeout_seconds))
        return CommandResult(command, 0, "", "", 0.1)


def test_containerlab_exposes_scoped_lifecycle_commands() -> None:
    executor = RecordingExecutor()
    runtime = Containerlab(executor, operation_timeout_seconds=30, query_timeout_seconds=5)
    topology = Path("build/aif-lab/topology.clab.yml")

    runtime.deploy(topology, reconfigure=True)
    runtime.destroy(topology)
    runtime.inspect(topology)
    runtime.inspect_all()

    assert executor.calls == [
        (
            (
                "containerlab",
                "deploy",
                "--topo",
                "build/aif-lab/topology.clab.yml",
                "--reconfigure",
            ),
            30,
        ),
        (
            (
                "containerlab",
                "destroy",
                "--topo",
                "build/aif-lab/topology.clab.yml",
                "--cleanup",
            ),
            30,
        ),
        (
            (
                "containerlab",
                "inspect",
                "--topo",
                "build/aif-lab/topology.clab.yml",
                "--format",
                "json",
            ),
            5,
        ),
        (("containerlab", "inspect", "--all", "--format", "json"), 5),
    ]


def test_containerlab_exec_targets_one_node_and_quotes_command_arguments() -> None:
    executor = RecordingExecutor()
    runtime = Containerlab(executor, query_timeout_seconds=7)

    runtime.exec(
        Path("topology.clab.yml"),
        "leaf-a1",
        ["vtysh", "-c", "show bgp ipv4 unicast json"],
    )

    assert executor.calls == [
        (
            (
                "containerlab",
                "exec",
                "--topo",
                "topology.clab.yml",
                "--label",
                "clab-node-name=leaf-a1",
                "--cmd",
                "vtysh -c 'show bgp ipv4 unicast json'",
                "--format",
                "json",
            ),
            7,
        )
    ]


def test_containerlab_exec_requires_argv_not_shell_text() -> None:
    runtime = Containerlab(RecordingExecutor())

    with pytest.raises(TypeError, match="argv"):
        runtime.exec(Path("topology.clab.yml"), "leaf-a1", "ip link")
