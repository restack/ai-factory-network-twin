"""Command-line interface for aftwin."""

import json
import sys
from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from cyclopts import App
from pydantic import ValidationError
from yaml import YAMLError

from aftwin import __version__
from aftwin.assure.runner import run_assurance
from aftwin.compiler.compiler import compile_fabric, load_platform_map
from aftwin.domain.models import Fabric
from aftwin.domain.types import validate_identifier
from aftwin.errors import (
    AftwinError,
    CompilationError,
    ExitCode,
    FixtureError,
    NetBoxOperationError,
    PolicyProfileError,
    RuntimeVerificationError,
    SourceValidationError,
)
from aftwin.netbox.adapter import NetBoxAdapter
from aftwin.netbox.client import NetBoxClient
from aftwin.netbox.fixture import load_fixture
from aftwin.netbox.seeder import NetBoxSeeder
from aftwin.policy.engine import PolicyEngine
from aftwin.policy.findings import ValidationReport
from aftwin.policy.profile import PolicyProfile, load_policy_profile
from aftwin.runtime.containerlab import Containerlab
from aftwin.runtime.executor import SubprocessExecutor
from aftwin.runtime.images import DockerImagePreflight
from aftwin.runtime.lifecycle import LabLifecycle, LabLifecycleError
from aftwin.scenario.models import load_scenario
from aftwin.scenario.runner import ScenarioRunner
from aftwin.settings import Settings
from aftwin.verify.verifier import RuntimeVerifier

OutputFormat = Literal["human", "json"]

app = App(
    name="aftwin",
    help="NetBox-driven AI cluster network digital twin and validation lab.",
    version=__version__,
)
lab = App(name="lab", help="Manage the local Containerlab lifecycle.")
scenario_app = App(name="scenario", help="Run reversible fabric failure scenarios.")
app.command(lab)
app.command(scenario_app)


@app.command
def seed(
    fixture: Path = Path("fixtures/mini-dual-plane.yaml"),
    *,
    allow_nonlocal: bool = False,
    output: OutputFormat = "human",
) -> None:
    """Idempotently seed a development NetBox fixture."""
    settings = Settings()
    if settings.netbox_token is None:
        raise NetBoxOperationError("authenticate", "NETBOX_TOKEN is not configured")
    _require_local_seed_target(settings.netbox_url, allow_nonlocal=allow_nonlocal)
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
    site: str | None = None,
    *,
    tag: str | None = None,
    profile: Path = Path("config/policies/mini-dual-plane.yaml"),
    output: OutputFormat = "human",
) -> None:
    """Fetch, normalize, and statically validate NetBox source data."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    tag = _resolve_optional_identifier(tag, field="tag")
    if settings.netbox_token is None:
        raise NetBoxOperationError("authenticate", "NETBOX_TOKEN is not configured")
    try:
        policy_profile = load_policy_profile(profile)
    except (OSError, ValidationError, YAMLError) as error:
        raise PolicyProfileError(str(profile), str(error)) from error

    adapter = NetBoxAdapter(NetBoxClient(settings.netbox_url, settings.netbox_token))
    snapshot = adapter.fetch_site(site, tag_slug=tag)
    adapter.save_snapshot(snapshot, settings.build_dir / site / "source" / "netbox.json")
    _, report = _normalize_and_validate(adapter, snapshot, policy_profile)
    report_path = settings.build_dir / site / "reports" / "static-validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    rendered = report.to_json() if output == "json" else report.render_human()
    print(rendered, end="")
    if report.failed:
        raise SystemExit(ExitCode.SOURCE_VALIDATION)


@app.command
def compile(
    site: str | None = None,
    *,
    tag: str | None = None,
    profile: Path = Path("config/policies/mini-dual-plane.yaml"),
    platform_map: Path = Path("config/platform-map.yaml"),
    output: OutputFormat = "human",
) -> None:
    """Fetch, validate, and compile topology and configuration artifacts."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    tag = _resolve_optional_identifier(tag, field="tag")
    if settings.netbox_token is None:
        raise NetBoxOperationError("authenticate", "NETBOX_TOKEN is not configured")
    try:
        policy_profile = load_policy_profile(profile)
    except (OSError, ValidationError, YAMLError) as error:
        raise PolicyProfileError(str(profile), str(error)) from error

    adapter = NetBoxAdapter(NetBoxClient(settings.netbox_url, settings.netbox_token))
    snapshot = adapter.fetch_site(site, tag_slug=tag)
    site_dir = settings.build_dir / site
    adapter.save_snapshot(snapshot, site_dir / "source" / "netbox.json")
    fabric, report = _normalize_and_validate(adapter, snapshot, policy_profile)
    report_path = site_dir / "reports" / "static-validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    if report.failed:
        print(report.to_json() if output == "json" else report.render_human(), end="")
        raise SystemExit(ExitCode.SOURCE_VALIDATION)
    try:
        platform_mapping = load_platform_map(platform_map)
        result = compile_fabric(fabric, platform_mapping, policy_profile, site_dir)
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
    site: str | None = None, *, reconfigure: bool = False, output: OutputFormat = "human"
) -> None:
    """Deploy a statically validated compiled lab."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    lifecycle = _lab_lifecycle()
    result = lifecycle.deploy(settings.build_dir / site, reconfigure=reconfigure)
    payload = {"site": site, "operation": "deploy", "changed": result.changed, "running": True}
    if output == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"Lab deployed for site '{site}'.")


@app.command
def verify(site: str | None = None, *, output: OutputFormat = "human") -> None:
    """Verify BGP, routes, reachability, and plane isolation."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    site_dir = settings.build_dir / site
    containerlab = _containerlab()
    try:
        inspection = LabLifecycle(containerlab).inspect(site_dir)
    except LabLifecycleError as error:
        raise RuntimeVerificationError(error.message, details=error.details) from error
    if not inspection.running:
        raise RuntimeVerificationError("the lab is not running", details={"site": site})
    report = RuntimeVerifier(containerlab).verify(site_dir)
    print(report.to_json() if output == "json" else report.render_human(), end="")
    if not report.passed:
        raise SystemExit(ExitCode.VERIFICATION)


@app.command
def assure(
    site: str | None = None,
    *,
    batfish_host: str = "localhost",
    output: OutputFormat = "human",
) -> None:
    """Run optional Batfish pre-deployment assurance on the compiled build."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    report = run_assurance(settings.build_dir / site, host=batfish_host)
    print(report.to_json() if output == "json" else report.render_human(), end="")
    if not report.passed:
        raise SystemExit(ExitCode.ASSURANCE)


@lab.command(name="up")
def lab_up(
    site: str | None = None,
    *,
    tag: str | None = None,
    profile: Path = Path("config/policies/mini-dual-plane.yaml"),
    platform_map: Path = Path("config/platform-map.yaml"),
    output: OutputFormat = "human",
) -> None:
    """Compile and deploy the local lab."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    _lab_lifecycle().require_absent_before_compile(settings.build_dir / site)
    compile(
        site=site,
        tag=tag,
        profile=profile,
        platform_map=platform_map,
        output=output,
    )
    deploy(site=site, output=output)


@lab.command(name="test")
def lab_test(site: str | None = None, *, output: OutputFormat = "human") -> None:
    """Verify the local lab."""
    verify(site=site, output=output)


@lab.command(name="down")
def lab_down(site: str | None = None, *, output: OutputFormat = "human") -> None:
    """Destroy the local lab and remove its runtime working directory."""
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    result = _lab_lifecycle().destroy(settings.build_dir / site)
    payload = {
        "site": site,
        "operation": "destroy",
        "changed": result.changed,
        "running": False,
    }
    if output == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        action = "destroyed" if result.changed else "already absent"
        print(f"Lab {action} for site '{site}'.")


@scenario_app.command(name="run")
def scenario_run(
    path: Path = Path("scenarios/link-failure.yaml"),
    *,
    site: str | None = None,
    output: OutputFormat = "human",
) -> None:
    """Run one reversible failure scenario against a healthy lab."""
    try:
        scenario = load_scenario(path)
    except (OSError, ValidationError, YAMLError) as error:
        raise RuntimeVerificationError(
            f"failure scenario is invalid: {path}", details={"path": path.as_posix()}
        ) from error
    settings = Settings()
    site = _resolve_identifier(settings.site if site is None else site, field="site")
    site_dir = settings.build_dir / site
    containerlab = _containerlab()
    try:
        inspection = LabLifecycle(containerlab).inspect(site_dir)
    except LabLifecycleError as error:
        raise RuntimeVerificationError(error.message, details=error.details) from error
    if not inspection.running:
        raise RuntimeVerificationError("the lab is not running", details={"site": site})
    report = ScenarioRunner(containerlab, RuntimeVerifier(containerlab)).run(site_dir, scenario)
    print(report.to_json() if output == "json" else report.render_human(), end="")
    if not report.passed:
        raise SystemExit(ExitCode.VERIFICATION)


def _containerlab() -> Containerlab:
    """Construct the default runtime boundary."""
    return Containerlab(SubprocessExecutor())


def _lab_lifecycle() -> LabLifecycle:
    """Construct the guarded lifecycle service."""
    return LabLifecycle(
        _containerlab(),
        image_preflight=DockerImagePreflight(SubprocessExecutor()),
    )


def _resolve_identifier(value: str, *, field: str) -> str:
    try:
        return validate_identifier(value, field=field)
    except ValueError as error:
        raise NetBoxOperationError("configure", str(error)) from error


def _resolve_optional_identifier(value: str | None, *, field: str) -> str | None:
    return None if value is None else _resolve_identifier(value, field=field)


def _normalize_and_validate(
    adapter: NetBoxAdapter, snapshot: dict[str, object], policy_profile: PolicyProfile
) -> tuple[Fabric, ValidationReport]:
    """Translate malformed external data into the stable source-error contract."""
    try:
        fabric = adapter.normalize(snapshot)
        report = PolicyEngine().validate(fabric, policy_profile)
    except NetBoxOperationError as error:
        raise SourceValidationError(error.message) from error
    except (ValueError, KeyError, StopIteration) as error:
        raise SourceValidationError(f"{type(error).__name__}: {error}") from error
    return fabric, report


def _require_local_seed_target(url: str, *, allow_nonlocal: bool) -> None:
    if allow_nonlocal:
        return
    hostname = urlparse(url).hostname
    local = hostname == "localhost"
    if hostname is not None and not local:
        try:
            local = ip_address(hostname).is_loopback
        except ValueError:
            local = False
    if not local:
        raise NetBoxOperationError(
            "seed safety",
            "refusing a non-loopback NetBox target; pass --allow-nonlocal explicitly",
        )


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
