"""Structured application errors and stable exit codes."""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    """Public CLI exit-code contract."""

    SUCCESS = 0
    SOURCE_VALIDATION = 2
    COMPILE = 3
    DEPLOYMENT = 4
    VERIFICATION = 5
    CONFIGURATION = 10


@dataclass(slots=True)
class AftwinError(Exception):
    """An expected failure that can be rendered safely for CLI consumers."""

    code: str
    message: str
    exit_code: ExitCode
    details: dict[str, Any] = field(default_factory=dict[str, Any])

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        """Return a machine-readable representation without secret context."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class NotImplementedCommandError(AftwinError):
    """A command whose implementation belongs to a later milestone."""

    def __init__(self, command: str, milestone: str) -> None:
        super().__init__(
            code="command_not_implemented",
            message=f"'{command}' is planned for {milestone} and is not implemented yet.",
            exit_code=ExitCode.CONFIGURATION,
            details={"command": command, "milestone": milestone},
        )
