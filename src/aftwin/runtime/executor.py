"""Safe, injectable subprocess execution for runtime integrations."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured evidence from one completed subprocess."""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        """Whether the process returned a successful exit status."""
        return self.returncode == 0


class CommandFailureKind(StrEnum):
    """Stable failure categories for callers and reports."""

    NOT_FOUND = "not_found"
    TIMED_OUT = "timed_out"
    START_FAILED = "start_failed"
    NON_ZERO_EXIT = "non_zero_exit"


class CommandExecutionError(Exception):
    """A structured subprocess failure with captured, non-streamed evidence."""

    def __init__(
        self,
        *,
        kind: CommandFailureKind,
        argv: tuple[str, ...],
        message: str,
        timeout_seconds: float,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.argv = argv
        self.timeout_seconds = timeout_seconds
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def as_dict(self) -> dict[str, object]:
        """Return stable machine-readable evidence for higher-level errors."""
        return {
            "kind": self.kind.value,
            "argv": list(self.argv),
            "timeout_seconds": self.timeout_seconds,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


class CommandExecutor(Protocol):
    """Minimal execution boundary consumed by runtime adapters."""

    def run(self, argv: Sequence[str], *, timeout_seconds: float | None = None) -> CommandResult:
        """Execute one argv array and return captured evidence."""
        ...


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


class SubprocessExecutor:
    """Execute argv arrays without a shell and with a bounded timeout."""

    def __init__(
        self,
        *,
        default_timeout_seconds: float = 120.0,
        maximum_timeout_seconds: float = 900.0,
        cwd: Path | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        if maximum_timeout_seconds <= 0:
            raise ValueError("maximum_timeout_seconds must be positive")
        if default_timeout_seconds > maximum_timeout_seconds:
            raise ValueError("default timeout cannot exceed maximum timeout")
        self._default_timeout_seconds = default_timeout_seconds
        self._maximum_timeout_seconds = maximum_timeout_seconds
        self._cwd = cwd

    def run(self, argv: Sequence[str], *, timeout_seconds: float | None = None) -> CommandResult:
        """Run a subprocess, capturing output and translating expected failures."""
        if isinstance(argv, str):
            raise TypeError("argv must be a sequence of arguments, not a shell command")
        command = tuple(argv)
        if not command or not command[0]:
            raise ValueError("argv must contain a non-empty executable")
        timeout = self._default_timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0 or timeout > self._maximum_timeout_seconds:
            raise ValueError(
                f"timeout_seconds must be greater than zero and at most "
                f"{self._maximum_timeout_seconds:g}"
            )

        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self._cwd,
                capture_output=True,
                check=False,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as error:
            raise CommandExecutionError(
                kind=CommandFailureKind.NOT_FOUND,
                argv=command,
                message=f"runtime executable was not found: {command[0]}",
                timeout_seconds=timeout,
            ) from error
        except subprocess.TimeoutExpired as error:
            raise CommandExecutionError(
                kind=CommandFailureKind.TIMED_OUT,
                argv=command,
                message=f"runtime command exceeded its {timeout:g}s timeout",
                timeout_seconds=timeout,
                stdout=_timeout_text(error.stdout),
                stderr=_timeout_text(error.stderr),
            ) from error
        except OSError as error:
            raise CommandExecutionError(
                kind=CommandFailureKind.START_FAILED,
                argv=command,
                message=f"runtime command could not start: {error}",
                timeout_seconds=timeout,
            ) from error

        result = CommandResult(
            argv=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=time.monotonic() - started,
        )
        if not result.succeeded:
            raise CommandExecutionError(
                kind=CommandFailureKind.NON_ZERO_EXIT,
                argv=command,
                message=f"runtime command exited with status {result.returncode}",
                timeout_seconds=timeout,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result
