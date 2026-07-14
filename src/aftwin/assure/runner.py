"""Orchestrate optional Batfish pre-deployment assurance for one build."""

import shutil
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from aftwin.assure.batfish import BatfishAnswers, collect_batfish_answers
from aftwin.assure.questions import (
    check_bgp_sessions,
    check_derived_routes,
    check_isolation,
    check_loops,
    check_parse,
)
from aftwin.assure.report import AssuranceReport, AssuranceSection
from aftwin.backend.capabilities import BackendCapability
from aftwin.backend.contract import BackendRoleClass
from aftwin.backend.registry import get_backend
from aftwin.compiler.expected_state import ExpectedState
from aftwin.compiler.manifest import (
    InventoryMetadata,
    ManifestIntegrityError,
    load_verified_manifest,
)
from aftwin.errors import AssuranceError

REQUIRED_ASSURANCE_ARTIFACTS = ("expected-state.json", "inventory.json")
SNAPSHOT_DIR = Path("batfish/snapshot")
REPORT_PATH = Path("reports/batfish-assurance.json")

type AnswerCollector = Callable[..., BatfishAnswers]


def _load_inventory(site_dir: Path) -> InventoryMetadata:
    path = site_dir / "inventory.json"
    try:
        inventory = InventoryMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise AssuranceError(
            f"compiled inventory is unreadable or invalid: {path}",
            details={"path": path.as_posix()},
        ) from error
    if not inventory.nodes:
        raise AssuranceError(
            "compiled inventory has no node renderer records; recompile this build",
            details={"path": path.as_posix()},
        )
    return inventory


def _load_expected(site_dir: Path) -> ExpectedState:
    path = site_dir / "expected-state.json"
    try:
        return ExpectedState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise AssuranceError(
            f"expected state is unreadable or invalid: {path}",
            details={"path": path.as_posix()},
        ) from error


def _network_config_sources(site_dir: Path, inventory: InventoryMetadata) -> dict[str, Path]:
    """Resolve each network node's Batfish-admitted configuration file."""
    sources: dict[str, Path] = {}
    unsupported: list[str] = []
    for record in inventory.nodes:
        try:
            backend = get_backend(record.renderer)
        except ValueError as error:
            raise AssuranceError(
                f"compiled inventory names an unknown renderer for {record.name}: {error}",
                details={"node": record.name, "renderer": record.renderer},
            ) from error
        if backend.role_class is not BackendRoleClass.NETWORK:
            continue
        config_path = backend.batfish_config_path(record.name)
        if BackendCapability.BATFISH_ASSURANCE not in backend.capabilities or config_path is None:
            unsupported.append(f"{record.name} ({record.renderer})")
            continue
        sources[record.name] = site_dir / config_path
    if unsupported:
        raise AssuranceError(
            "the selected backend does not advertise Batfish assurance for: "
            + ", ".join(sorted(unsupported)),
            details={"unsupported_nodes": sorted(unsupported)},
        )
    if not sources:
        raise AssuranceError("the build contains no network nodes to assure")
    return sources


def _build_snapshot(site_dir: Path, sources: dict[str, Path]) -> Path:
    snapshot_dir = site_dir / SNAPSHOT_DIR
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    configs_dir = snapshot_dir / "configs"
    configs_dir.mkdir(parents=True)
    for node, source in sorted(sources.items()):
        if not source.is_file():
            raise AssuranceError(
                f"configuration for {node} does not exist: {source}",
                details={"node": node, "path": source.as_posix()},
            )
        (configs_dir / f"{node}.cfg").write_bytes(source.read_bytes())
    return snapshot_dir


def run_assurance(
    site_dir: Path,
    *,
    host: str = "localhost",
    collector: AnswerCollector = collect_batfish_answers,
) -> AssuranceReport:
    """Produce and persist a deterministic Batfish assurance report."""
    try:
        manifest = load_verified_manifest(site_dir, required=REQUIRED_ASSURANCE_ARTIFACTS)
    except ManifestIntegrityError as error:
        raise AssuranceError(str(error), details=dict(error.details)) from error
    inventory = _load_inventory(site_dir)
    expected = _load_expected(site_dir)
    snapshot_dir = _build_snapshot(site_dir, _network_config_sources(site_dir, inventory))

    answers = collector(
        snapshot_dir,
        host=host,
        network=f"aftwin-{expected.site}",
        snapshot=f"build-{manifest.build_hash[:12]}",
    )

    parse = check_parse(answers.parse_files, answers.parse_issues)
    sections: tuple[AssuranceSection, ...]
    if parse.successful:
        sections = (
            parse,
            check_bgp_sessions(answers.session_compatibility, answers.session_status, expected),
            check_loops(answers.loops),
            check_derived_routes(answers.bgp_routes, expected),
            check_isolation(answers.bgp_routes, expected),
        )
    else:
        # Unsupported syntax disables the capability explicitly instead of
        # reporting partial assurance from the remaining questions.
        sections = (parse,)

    report = AssuranceReport(
        build_hash=manifest.build_hash,
        source_revision=manifest.source_revision,
        syntax_supported=parse.successful,
        sections=sections,
    )
    report_path = site_dir / REPORT_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
    return report
