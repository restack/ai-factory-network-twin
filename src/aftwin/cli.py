"""Command-line interface for aftwin."""

import json
import sys
from pathlib import Path
from typing import Literal, NoReturn

from cyclopts import App
from pydantic import ValidationError
from yaml import YAMLError

from aftwin import __version__
from aftwin.compiler.compiler import compile_fabric, load_platform_map
from aftwin.errors import (
    AftwinError,
    CompilationError,
    ExitCode,
    FixtureError,
    NetBoxOperationError,
    NotImplementedCommandError,
    PolicyProfileError,
    SourceValidationError,
)
from aftwin.netbox.adapter import NetBoxAdapter
from aftwin.netbox.client import NetBoxClient
from aftwin.netbox.fixture import load_fixture
from aftwin.netbox.seeder import NetBoxSeeder
from aftwin.policy.engine import PolicyEngine
from aftwin.policy.profile import load_policy_profile
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
def validate(
    site: str = "aif-lab",
    *,
    profile: Path = Path("config/policies/mini-dual-plane.yaml"),
    output: OutputFormat = "human",
) -> None:
    """Fetch, normalize, and statically validate NetBox source data."""
    settings = Settings()
    if settings.netbox_token is None:
        raise NetBoxOperationError("authenticate", "NETBOX_TOKEN is not configured")
    try:
        policy_profile = load_policy_profile(profile)
    except (OSError, ValidationError, YAMLError) as error:
        raise PolicyProfileError(str(profile), str(error)) from error

    adapter = NetBoxAdapter(NetBoxClient(settings.netbox_url, settings.netbox_token))
    snapshot = adapter.fetch_site(site)
    adapter.save_snapshot(snapshot, settings.build_dir / site / "source" / "netbox.json")
    try:
        fabric = adapter.normalize(snapshot)
    except NetBoxOperationError as error:
        raise SourceValidationError(error.message) from error
    report = PolicyEngine().validate(fabric, policy_profile)
    report_path = settings.build_dir / site / "reports" / "static-validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    rendered = report.to_json() if output == "json" else report.render_human()
    print(rendered, end="")
    if report.failed:
        raise SystemExit(ExitCode.SOURCE_VALIDATION)


@app.command
def compile(site: str = "aif-lab", *, output: OutputFormat = "human") -> None:
    """Fetch, validate, and compile topology and configuration artifacts."""
    settings = Settings()
    if settings.netbox_token is None:
        raise NetBoxOperationError("authenticate", "NETBOX_TOKEN is not configured")
    profile_path = Path("config/policies/mini-dual-plane.yaml")
    platform_map_path = Path("config/platform-map.yaml")
    try:
        policy_profile = load_policy_profile(profile_path)
    except (OSError, ValidationError, YAMLError) as error:
        raise PolicyProfileError(str(profile_path), str(error)) from error

    adapter = NetBoxAdapter(NetBoxClient(settings.netbox_url, settings.netbox_token))
    snapshot = adapter.fetch_site(site)
    site_dir = settings.build_dir / site
    adapter.save_snapshot(snapshot, site_dir / "source" / "netbox.json")
    try:
        fabric = adapter.normalize(snapshot)
    except NetBoxOperationError as error:
        raise SourceValidationError(error.message) from error
    report = PolicyEngine().validate(fabric, policy_profile)
    report_path = site_dir / "reports" / "static-validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    if report.failed:
        print(report.to_json() if output == "json" else report.render_human(), end="")
        raise SystemExit(ExitCode.SOURCE_VALIDATION)
    try:
        platform_map = load_platform_map(platform_map_path)
        result = compile_fabric(fabric, platform_map, policy_profile, site_dir)
    except (OSError, ValidationError, YAMLError, TypeError, ValueError) as error:
        raise CompilationError(str(error)) from error
    payload = {
        "build_hash": result.build_hash,
        "fabric": result.fabric,
        "links": result.link_count,
        "nodes": result.node_count,
        "output_dir": result.output_dir.as_posix(),
        "site": result.site,
        "static_validation": "PASS",
    }
    if output == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"Static validation: PASS\nNodes compiled: {result.node_count}\n"
            f"Links compiled: {result.link_count}\nBuild hash: {result.build_hash}\n"
            f"Output: {result.output_dir.as_posix()}"
        )


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
