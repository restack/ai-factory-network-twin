"""Typed command boundary for Containerlab."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

from aftwin.runtime.executor import CommandExecutor, CommandResult


class Containerlab:
    """Build and execute Containerlab commands through one injected executor."""

    def __init__(
        self,
        executor: CommandExecutor,
        *,
        executable: str = "containerlab",
        operation_timeout_seconds: float = 600.0,
        query_timeout_seconds: float = 120.0,
    ) -> None:
        if not executable:
            raise ValueError("executable must not be empty")
        if operation_timeout_seconds <= 0 or query_timeout_seconds <= 0:
            raise ValueError("Containerlab timeouts must be positive")
        self._executor = executor
        self._executable = executable
        self._operation_timeout_seconds = operation_timeout_seconds
        self._query_timeout_seconds = query_timeout_seconds

    def deploy(self, topology: Path, *, reconfigure: bool = False) -> CommandResult:
        """Deploy one topology, optionally allowing Containerlab reconfiguration."""
        argv = [self._executable, "deploy", "--topo", str(topology)]
        if reconfigure:
            argv.append("--reconfigure")
        return self._executor.run(argv, timeout_seconds=self._operation_timeout_seconds)

    def destroy(self, topology: Path, *, cleanup: bool = True) -> CommandResult:
        """Destroy resources belonging to one topology only."""
        argv = [self._executable, "destroy", "--topo", str(topology)]
        if cleanup:
            argv.append("--cleanup")
        return self._executor.run(argv, timeout_seconds=self._operation_timeout_seconds)

    def inspect(self, topology: Path) -> CommandResult:
        """Inspect one topology using Containerlab's machine-readable output."""
        return self._executor.run(
            [self._executable, "inspect", "--topo", str(topology), "--format", "json"],
            timeout_seconds=self._query_timeout_seconds,
        )

    def inspect_all(self) -> CommandResult:
        """Inspect every lab so callers can safely detect partial deployments."""
        return self._executor.run(
            [self._executable, "inspect", "--all", "--format", "json"],
            timeout_seconds=self._query_timeout_seconds,
        )

    def exec(self, topology: Path, node: str, command: Sequence[str]) -> CommandResult:
        """Execute an argv-style command in exactly one named lab node."""
        if not node:
            raise ValueError("node must not be empty")
        if isinstance(command, str):
            raise TypeError("command must be an argv sequence")
        command_argv = tuple(command)
        if not command_argv or any(not item for item in command_argv):
            raise ValueError("command must contain non-empty arguments")
        return self._executor.run(
            [
                self._executable,
                "exec",
                "--topo",
                str(topology),
                "--label",
                f"clab-node-name={node}",
                "--cmd",
                shlex.join(command_argv),
                "--format",
                "json",
            ],
            timeout_seconds=self._query_timeout_seconds,
        )
