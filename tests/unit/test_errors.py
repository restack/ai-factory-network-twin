from aftwin.errors import ExitCode, NotImplementedCommandError


def test_structured_error_is_machine_readable() -> None:
    error = NotImplementedCommandError("compile", "M3")

    assert error.exit_code is ExitCode.CONFIGURATION
    assert error.as_dict() == {
        "error": {
            "code": "command_not_implemented",
            "message": "'compile' is planned for M3 and is not implemented yet.",
            "details": {"command": "compile", "milestone": "M3"},
        }
    }
