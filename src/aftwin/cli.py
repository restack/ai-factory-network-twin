"""Command-line interface for aftwin."""

import json
import sys
from pathlib import Path
from typing import Literal, NoReturn

from cyclopts import App
from pydantic import ValidationError
from yaml import YAMLError

from aftwin import __version__
from aftwin.errors import (
    AftwinError,
    FixtureError,
    NetBoxOperationError,
    NotImplementedCommandError,
)
from aftwin.netbox.client import NetBoxClient
from aftwin.netbox.fixture import load_fixture
from aftwin.netbox.seeder import NetBoxSeeder
from aftwin.settings import Settings

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
def seed(
    fixture: Path = Path("fixtures/mini-dual-plane.yaml"), *, output: OutputFormat = "human"
) -> None:
    """Idempotently seed a development NetBox fixture."""
    settings = Settings()
    if settings.netbox_token is None:
        raise NetBoxOperationError("authenticate", "NETBOX_TOKEN is not configured")
    try:
        fixture_model = load_fixture(fixture)
    except (OSError, ValidationError, YAMLError) as error:
        raise FixtureError(str(fixture), str(error)) from error
    result = NetBoxSeeder(NetBoxClient(settings.netbox_url, settings.netbox_token)).seed(
        fixture_model
    )
    payload = {"fixture": fixture_model.name, "site": fixture_model.site.slug, **result.as_dict()}
    if output == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"Seeded fixture '{fixture_model.name}' for site '{fixture_model.site.slug}': "
            f"{result.created} created, {result.existing} existing."
        )


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
