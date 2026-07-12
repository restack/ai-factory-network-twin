"""Command-line interface for aftwin."""

import json
import sys
from typing import Literal, NoReturn

from cyclopts import App

from aftwin import __version__
from aftwin.errors import AftwinError, NotImplementedCommandError

OutputFormat = Literal["human", "json"]

app = App(
    name="aftwin",
    help="NetBox-driven AI cluster network digital twin and validation lab.",
    version=__version__,
)
lab = App(name="lab", help="Manage the local Containerlab lifecycle.")
app.command(lab)


def _pending(command: str, milestone: str) -> NoReturn:
    raise NotImplementedCommandError(command, milestone)


@app.command
def seed(fixture: str = "fixtures/mini-dual-plane.yaml", *, output: OutputFormat = "human") -> None:
    """Seed a development NetBox fixture (planned for M1)."""
    del fixture, output
    _pending("seed", "M1")


@app.command
def validate(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Validate NetBox source data (planned for M2)."""
    del site, output
    _pending("validate", "M2")


@app.command
def compile(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Compile topology and configuration artifacts (planned for M3)."""
    del site, output
    _pending("compile", "M3")


@app.command
def deploy(
    site: str = "aif-lab", *, reconfigure: bool = False, output: OutputFormat = "human"
) -> None:
    """Deploy a compiled lab (planned for M4)."""
    del site, reconfigure, output
    _pending("deploy", "M4")


@app.command
def verify(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Verify a running lab (planned for M4)."""
    del site, output
    _pending("verify", "M4")


@lab.command(name="up")
def lab_up(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Compile and deploy the local lab (planned for M4)."""
    del site, output
    _pending("lab up", "M4")


@lab.command(name="test")
def lab_test(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Verify the local lab (planned for M4)."""
    del site, output
    _pending("lab test", "M4")


@lab.command(name="down")
def lab_down(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Destroy the local lab (planned for M4)."""
    del site, output
    _pending("lab down", "M4")


def _render_error(error: AftwinError, output: OutputFormat) -> None:
    if output == "json":
        print(json.dumps(error.as_dict(), sort_keys=True), file=sys.stderr)
    else:
        print(f"Error [{error.code}]: {error.message}", file=sys.stderr)


def _requested_output(argv: list[str] | None) -> OutputFormat:
    if argv is None:
        argv = sys.argv[1:]
    for index, argument in enumerate(argv):
        if argument == "--output" and index + 1 < len(argv) and argv[index + 1] == "json":
            return "json"
        if argument == "--output=json":
            return "json"
    return "human"


def main(argv: list[str] | None = None) -> None:
    """Run the CLI and translate expected failures to stable exit codes."""
    output = _requested_output(argv)
    try:
        if argv is None:
            app()
        else:
            app(argv)
    except AftwinError as error:
        _render_error(error, output)
        raise SystemExit(error.exit_code) from error
