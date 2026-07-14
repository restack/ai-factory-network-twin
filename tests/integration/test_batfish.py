import os
from pathlib import Path

import pytest

from aftwin.assure.batfish import collect_batfish_answers
from aftwin.assure.questions import check_bgp_sessions, check_isolation, check_parse
from aftwin.assure.runner import run_assurance
from aftwin.compiler.compiler import compile_fabric, load_platform_map
from aftwin.compiler.expected_state import ExpectedState
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.profile import load_policy_profile

pytestmark = [
    pytest.mark.batfish,
    pytest.mark.skipif(
        os.getenv("AFTWIN_RUN_BATFISH_INTEGRATION") != "1",
        reason="set AFTWIN_RUN_BATFISH_INTEGRATION=1 with a running Batfish service",
    ),
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = PROJECT_ROOT / "tests/golden/mini-dual-plane"
HOST = os.getenv("BATFISH_HOST", "localhost")


def _expected() -> ExpectedState:
    return ExpectedState.model_validate_json((GOLDEN / "expected-state.json").read_text())


def test_golden_frr_build_passes_admitted_batfish_questions(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(PROJECT_ROOT / "fixtures/mini-dual-plane.yaml"))
    profile = load_policy_profile(PROJECT_ROOT / "config/policies/mini-dual-plane.yaml")
    compile_fabric(
        fabric,
        load_platform_map(PROJECT_ROOT / "config/platform-map.yaml"),
        profile,
        tmp_path,
    )

    report = run_assurance(tmp_path, host=HOST)

    assert report.syntax_supported, report.render_human()
    assert report.passed, report.render_human()
    assert {section.name for section in report.sections} == {
        "parse-status",
        "bgp-sessions",
        "forwarding-loops",
        "derived-routes",
        "cross-plane-isolation",
    }
    assert (tmp_path / "reports" / "batfish-assurance.json").is_file()


def _corrupted_snapshot(tmp_path: Path) -> Path:
    """Build a snapshot simulating renderer faults in two golden configs."""
    configs_dir = tmp_path / "fault-snapshot" / "configs"
    configs_dir.mkdir(parents=True)
    for router_dir in sorted((GOLDEN / "configs" / "routers").iterdir()):
        config = (router_dir / "frr.conf").read_text()
        if router_dir.name == "leaf-a1":
            # Session fault: the peer AS no longer matches spine-a1.
            config = config.replace(
                "neighbor 10.0.0.0 remote-as 65001", "neighbor 10.0.0.0 remote-as 65009"
            )
        if router_dir.name == "leaf-b1":
            # Isolation fault: a Plane B leaf attaches and advertises a
            # Plane A pool prefix, as a mis-addressed renderer would.
            config = config.replace("10.1.1.0/31", "10.0.9.0/31")
        (configs_dir / f"{router_dir.name}.cfg").write_text(config)
    return configs_dir.parent


def test_deliberate_faults_produce_stable_findings(tmp_path: Path) -> None:
    snapshot = _corrupted_snapshot(tmp_path)
    expected = _expected()

    answers = collect_batfish_answers(
        snapshot, host=HOST, network="aftwin-integration", snapshot="fault-variant"
    )
    parse = check_parse(answers.parse_files, answers.parse_issues)
    sessions = check_bgp_sessions(answers.session_compatibility, answers.session_status, expected)
    isolation = check_isolation(answers.bgp_routes, expected)

    assert parse.successful, [finding.as_dict() for finding in parse.findings]
    assert not sessions.successful
    session_targets = {
        (finding.rule_id, finding.target)
        for finding in sessions.findings
        if finding.target.startswith("leaf-a1->spine-a1")
        or finding.target.startswith("spine-a1->leaf-a1")
    }
    assert session_targets, sessions.findings
    assert not isolation.successful
    assert all(finding.rule_id == "BFA008" for finding in isolation.findings)
    assert any("10.0.9.0/31" in finding.target for finding in isolation.findings)

    repeat = collect_batfish_answers(
        snapshot, host=HOST, network="aftwin-integration", snapshot="fault-variant"
    )
    assert (
        check_bgp_sessions(repeat.session_compatibility, repeat.session_status, expected)
        == sessions
    )
    assert check_isolation(repeat.bgp_routes, expected) == isolation


def test_unadmitted_syntax_disables_the_capability(tmp_path: Path) -> None:
    configs_dir = tmp_path / "alien-snapshot" / "configs"
    configs_dir.mkdir(parents=True)
    for router_dir in sorted((GOLDEN / "configs" / "routers").iterdir()):
        config = (router_dir / "frr.conf").read_text()
        if router_dir.name == "leaf-a1":
            config = config.replace(
                "ip forwarding\n", "ip forwarding\naftwin-alien-stanza enable\n"
            )
        (configs_dir / f"{router_dir.name}.cfg").write_text(config)

    answers = collect_batfish_answers(
        configs_dir.parent, host=HOST, network="aftwin-integration", snapshot="alien-variant"
    )
    parse = check_parse(answers.parse_files, answers.parse_issues)

    assert not parse.successful
    assert any(finding.rule_id in {"BFA001", "BFA002"} for finding in parse.findings)
