from pathlib import Path
from typing import Any

import pytest

from aftwin.assure.batfish import BatfishAnswers
from aftwin.assure.questions import (
    check_bgp_sessions,
    check_derived_routes,
    check_isolation,
    check_loops,
    check_parse,
)
from aftwin.assure.runner import run_assurance
from aftwin.compiler.compiler import compile_fabric, load_platform_map
from aftwin.compiler.expected_state import ExpectedState
from aftwin.errors import AssuranceError
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.profile import load_policy_profile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = PROJECT_ROOT / "tests/golden/mini-dual-plane"
EXPECTED = ExpectedState.model_validate_json((GOLDEN / "expected-state.json").read_text())
ROUTERS = sorted(
    {
        router.node
        for adjacency in EXPECTED.bgp_adjacencies
        for router in (adjacency.leaf, adjacency.spine)
    }
)


def _passing_parse_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files = [
        {
            "File_Name": f"configs/{router}.cfg",
            "Status": "PARTIALLY_UNRECOGNIZED",
            "File_Format": "CISCO_IOS",
            "Nodes": [router],
        }
        for router in ROUTERS
    ]
    issues = [
        {
            "Nodes": None,
            "Source_Lines": ["configs/leaf-a1.cfg:[2]"],
            "Type": "Parse warning",
            "Details": "This syntax is unrecognized",
            "Line_Text": line,
            "Parser_Context": "[cisco_configuration]",
        }
        for line in (
            "frr version 10.3.4",
            "frr defaults datacenter",
            "ip forwarding",
            "no bgp ebgp-requires-policy",
        )
    ]
    return files, issues


def _passing_session_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    compatibility: list[dict[str, Any]] = []
    status: list[dict[str, Any]] = []
    for adjacency in EXPECTED.bgp_adjacencies:
        for node, remote in (
            (adjacency.leaf.node, adjacency.spine.node),
            (adjacency.spine.node, adjacency.leaf.node),
        ):
            compatibility.append(
                {"Node": node, "Remote_Node": remote, "Configured_Status": "UNIQUE_MATCH"}
            )
            status.append(
                {"Node": node, "Remote_Node": remote, "Established_Status": "ESTABLISHED"}
            )
    return compatibility, status


def _passing_route_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for expectation in EXPECTED.router_prefixes:
        if expectation.protocol != "bgp":
            continue
        for index in range(max(expectation.min_next_hops, 1)):
            rows.append(
                {
                    "Node": expectation.router,
                    "VRF": "default",
                    "Network": str(expectation.prefix),
                    "Next_Hop_IP": f"192.0.2.{index + 1}",
                    "Protocol": "bgp",
                }
            )
    return rows


def _passing_answers(*args: Any, **kwargs: Any) -> BatfishAnswers:
    del args, kwargs
    files, issues = _passing_parse_rows()
    compatibility, status = _passing_session_rows()
    return BatfishAnswers(
        parse_files=tuple(files),
        parse_issues=tuple(issues),
        session_compatibility=tuple(compatibility),
        session_status=tuple(status),
        loops=(),
        bgp_routes=tuple(_passing_route_rows()),
    )


def test_parse_gate_accepts_only_the_admitted_warning_allowlist() -> None:
    files, issues = _passing_parse_rows()

    section = check_parse(files, issues)

    assert section.successful
    assert section.expected == len(ROUTERS)


def test_parse_gate_rejects_unlisted_syntax_and_foreign_formats() -> None:
    files, issues = _passing_parse_rows()
    issues.append(
        {
            "Nodes": None,
            "Source_Lines": ["configs/leaf-a1.cfg:[40]"],
            "Type": "Parse warning",
            "Details": "This syntax is unrecognized",
            "Line_Text": "segment-routing srv6",
        }
    )
    files[0] = dict(files[0]) | {"File_Format": "CUMULUS_CONCATENATED"}
    files[1] = dict(files[1]) | {"Status": "FAILED"}

    section = check_parse(files, issues)

    assert not section.successful
    rule_ids = [finding.rule_id for finding in section.findings]
    assert rule_ids.count("BFA001") == 2
    assert rule_ids.count("BFA002") == 1


def test_bgp_sessions_match_expected_adjacencies() -> None:
    compatibility, status = _passing_session_rows()

    section = check_bgp_sessions(compatibility, status, EXPECTED)

    assert section.successful
    assert section.expected == 16


def test_bgp_sessions_report_missing_extra_and_unestablished() -> None:
    compatibility, status = _passing_session_rows()
    removed = compatibility.pop(0)
    compatibility.append(
        {"Node": "leaf-a1", "Remote_Node": "spine-b1", "Configured_Status": "UNIQUE_MATCH"}
    )
    status[1] = dict(status[1]) | {"Established_Status": "NOT_ESTABLISHED"}

    section = check_bgp_sessions(compatibility, status, EXPECTED)

    assert not section.successful
    rule_ids = sorted(finding.rule_id for finding in section.findings)
    assert rule_ids == ["BFA003", "BFA004", "BFA005"]
    missing = next(finding for finding in section.findings if finding.rule_id == "BFA003")
    assert missing.target == f"{removed['Node']}->{removed['Remote_Node']}"


def test_loop_and_route_answers_convert_to_findings() -> None:
    assert check_loops(()).successful

    loop_section = check_loops(({"Flow": "start=leaf-a1 dst=10.0.1.4"},))
    assert not loop_section.successful
    assert loop_section.findings[0].rule_id == "BFA006"

    routes = _passing_route_rows()
    section = check_derived_routes(routes, EXPECTED)
    assert section.successful

    first_bgp = next(item for item in EXPECTED.router_prefixes if item.protocol == "bgp")
    reduced = [
        row
        for row in routes
        if not (row["Node"] == first_bgp.router and row["Network"] == str(first_bgp.prefix))
    ]
    degraded = check_derived_routes(reduced, EXPECTED)
    assert not degraded.successful
    assert degraded.findings[0].rule_id == "BFA007"


def test_isolation_rejects_cross_plane_route_leaks() -> None:
    routes = _passing_route_rows()
    assert check_isolation(routes, EXPECTED).successful

    plane_a_router = next(
        item.router for item in EXPECTED.router_prefixes if item.plane.value == "a"
    )
    forbidden_pool = next(
        contract.forbidden_route_pools[0]
        for contract in EXPECTED.isolation
        if contract.source_plane.value == "a"
    )
    routes.append(
        {
            "Node": plane_a_router,
            "VRF": "default",
            "Network": str(next(forbidden_pool.subnets(new_prefix=31))),
            "Next_Hop_IP": "192.0.2.9",
            "Protocol": "bgp",
        }
    )

    section = check_isolation(routes, EXPECTED)

    assert not section.successful
    assert section.findings[0].rule_id == "BFA008"


def _compile_golden(tmp_path: Path) -> Path:
    fabric = fixture_to_fabric(load_fixture(PROJECT_ROOT / "fixtures/mini-dual-plane.yaml"))
    profile = load_policy_profile(PROJECT_ROOT / "config/policies/mini-dual-plane.yaml")
    compile_fabric(
        fabric,
        load_platform_map(PROJECT_ROOT / "config/platform-map.yaml"),
        profile,
        tmp_path,
    )
    return tmp_path


def test_run_assurance_produces_a_deterministic_passing_report(tmp_path: Path) -> None:
    site_dir = _compile_golden(tmp_path)

    report = run_assurance(site_dir, collector=_passing_answers)
    report_bytes = (site_dir / "reports" / "batfish-assurance.json").read_bytes()
    second = run_assurance(site_dir, collector=_passing_answers)

    assert report.passed
    assert report.syntax_supported
    assert report.evidence_source == "batfish"
    assert report.fidelity_claim == "generated-configuration"
    assert {section.name for section in report.sections} == {
        "parse-status",
        "bgp-sessions",
        "forwarding-loops",
        "derived-routes",
        "cross-plane-isolation",
    }
    assert report == second
    assert report_bytes == (site_dir / "reports" / "batfish-assurance.json").read_bytes()
    snapshot_configs = sorted(
        path.name for path in (site_dir / "batfish" / "snapshot" / "configs").iterdir()
    )
    assert snapshot_configs == [f"{router}.cfg" for router in ROUTERS]


def test_run_assurance_disables_capability_on_unsupported_syntax(tmp_path: Path) -> None:
    site_dir = _compile_golden(tmp_path)

    def bad_parse(*args: Any, **kwargs: Any) -> BatfishAnswers:
        answers = _passing_answers()
        issues = (
            *answers.parse_issues,
            {
                "Nodes": None,
                "Source_Lines": ["configs/leaf-a1.cfg:[9]"],
                "Type": "Parse warning",
                "Details": "This syntax is unrecognized",
                "Line_Text": "mpls ldp",
            },
        )
        return BatfishAnswers(
            parse_files=answers.parse_files,
            parse_issues=issues,
            session_compatibility=answers.session_compatibility,
            session_status=answers.session_status,
            loops=answers.loops,
            bgp_routes=answers.bgp_routes,
        )

    report = run_assurance(site_dir, collector=bad_parse)

    assert not report.passed
    assert not report.syntax_supported
    assert [section.name for section in report.sections] == ["parse-status"]


def test_run_assurance_rejects_backends_without_the_capability(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(PROJECT_ROOT / "fixtures/mini-dual-plane-srlinux.yaml"))
    profile = load_policy_profile(PROJECT_ROOT / "config/policies/mini-dual-plane-srlinux.yaml")
    compile_fabric(
        fabric,
        load_platform_map(PROJECT_ROOT / "config/platform-map-srlinux.yaml"),
        profile,
        tmp_path,
    )

    with pytest.raises(AssuranceError, match="does not advertise Batfish assurance"):
        run_assurance(tmp_path, collector=_passing_answers)


def test_run_assurance_requires_manifest_integrity(tmp_path: Path) -> None:
    site_dir = _compile_golden(tmp_path)
    (site_dir / "expected-state.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AssuranceError, match="differs from manifest"):
        run_assurance(site_dir, collector=_passing_answers)
