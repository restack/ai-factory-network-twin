import sys

import pytest

from aftwin.runtime.executor import (
    CommandExecutionError,
    CommandFailureKind,
    SubprocessExecutor,
)


def test_executor_captures_stdout_stderr_and_argv() -> None:
    executor = SubprocessExecutor(default_timeout_seconds=2)

    result = executor.run(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ]
    )

    assert result.argv[0] == sys.executable
    assert result.returncode == 0
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.duration_seconds >= 0
    assert result.succeeded


def test_executor_returns_structured_nonzero_failure() -> None:
    executor = SubprocessExecutor(default_timeout_seconds=2)

    with pytest.raises(CommandExecutionError) as caught:
        executor.run(
            [
                sys.executable,
                "-c",
                "import sys; print('evidence', file=sys.stderr); raise SystemExit(7)",
            ]
        )

    error = caught.value
    assert error.kind is CommandFailureKind.NON_ZERO_EXIT
    assert error.returncode == 7
    assert error.stderr == "evidence\n"
    assert error.as_dict()["kind"] == "non_zero_exit"


def test_executor_enforces_timeout() -> None:
    executor = SubprocessExecutor(default_timeout_seconds=0.01)

    with pytest.raises(CommandExecutionError) as caught:
        executor.run([sys.executable, "-c", "import time; time.sleep(1)"])

    assert caught.value.kind is CommandFailureKind.TIMED_OUT
    assert caught.value.timeout_seconds == 0.01


def test_executor_reports_missing_executable() -> None:
    executor = SubprocessExecutor(default_timeout_seconds=1)

    with pytest.raises(CommandExecutionError) as caught:
        executor.run(["aftwin-command-that-does-not-exist"])

    assert caught.value.kind is CommandFailureKind.NOT_FOUND
    assert caught.value.returncode is None


def test_executor_rejects_shell_strings_and_unbounded_timeouts() -> None:
    executor = SubprocessExecutor(default_timeout_seconds=1, maximum_timeout_seconds=2)

    with pytest.raises(TypeError, match="argv"):
        executor.run("echo unsafe")
    with pytest.raises(ValueError, match="at most 2"):
        executor.run([sys.executable, "--version"], timeout_seconds=3)
