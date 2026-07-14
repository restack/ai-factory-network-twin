"""Convert admitted Batfish answers into project assurance findings.

Every function consumes plain answer records (one dict per frame row), so the
conversion logic stays independent of pybatfish and unit-testable with
recorded fixtures. The admitted answer set and the benign warning allowlist
were established by the M7 compatibility spike against the golden FRR lab.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from ipaddress import IPv4Network
from typing import Any

from aftwin.assure.report import AssuranceCategory, AssuranceFinding, AssuranceSection
from aftwin.compiler.expected_state import ExpectedState
from aftwin.domain.enums import FabricPlane

type AnswerRow = Mapping[str, Any]

ACCEPTED_PARSE_STATUSES = frozenset({"PASSED", "PARTIALLY_UNRECOGNIZED"})
ADMITTED_FILE_FORMAT = "CISCO_IOS"
# Benign FRR idioms that Batfish's admitted parser reports but does not need.
BENIGN_UNRECOGNIZED_LINES = frozenset(
    {
        "frr defaults datacenter",
        "ip forwarding",
        "no bgp ebgp-requires-policy",
    }
)
BENIGN_UNRECOGNIZED_PREFIXES = ("frr version ",)


def _text(row: AnswerRow, key: str) -> str:
    return str(row.get(key, "")).strip()


def _is_benign_issue(row: AnswerRow) -> bool:
    if _text(row, "Type") != "Parse warning":
        return False
    line = _text(row, "Line_Text")
    return line in BENIGN_UNRECOGNIZED_LINES or line.startswith(BENIGN_UNRECOGNIZED_PREFIXES)


def check_parse(files: Sequence[AnswerRow], issues: Sequence[AnswerRow]) -> AssuranceSection:
    """Gate the capability on fully admitted parse status and syntax."""
    findings: list[AssuranceFinding] = []
    passed = 0
    for row in files:
        file_name = _text(row, "File_Name") or "<unknown file>"
        status = _text(row, "Status")
        file_format = _text(row, "File_Format")
        if status not in ACCEPTED_PARSE_STATUSES:
            findings.append(
                AssuranceFinding(
                    rule_id="BFA001",
                    category=AssuranceCategory.PARSE,
                    target=file_name,
                    message=f"configuration parse status is {status or 'unknown'}",
                    hint="Inspect the generated configuration and the Batfish parse log.",
                )
            )
        elif file_format != ADMITTED_FILE_FORMAT:
            findings.append(
                AssuranceFinding(
                    rule_id="BFA001",
                    category=AssuranceCategory.PARSE,
                    target=file_name,
                    message=(
                        f"Batfish detected format {file_format or 'unknown'}; "
                        f"only {ADMITTED_FILE_FORMAT} is admitted for this renderer"
                    ),
                    hint="Re-run the compatibility spike before trusting this answer set.",
                )
            )
        else:
            passed += 1
    for row in issues:
        if _is_benign_issue(row):
            continue
        findings.append(
            AssuranceFinding(
                rule_id="BFA002",
                category=AssuranceCategory.PARSE,
                target=str(row.get("Source_Lines") or row.get("Nodes") or "<unknown>"),
                message=(
                    f"{_text(row, 'Type') or 'issue'}: "
                    f"{_text(row, 'Details') or 'unrecognized syntax'}"
                    + (f" ({_text(row, 'Line_Text')})" if _text(row, "Line_Text") else "")
                ),
                hint=(
                    "The generated syntax is outside the admitted allowlist; Batfish "
                    "assurance is disabled until the syntax is re-validated."
                ),
            )
        )
    return AssuranceSection(
        name="parse-status",
        expected=len(files),
        passed=passed,
        findings=tuple(findings),
    )


def _expected_directed_sessions(expected: ExpectedState) -> dict[tuple[str, str], None]:
    sessions: dict[tuple[str, str], None] = {}
    for adjacency in expected.bgp_adjacencies:
        sessions[(adjacency.leaf.node, adjacency.spine.node)] = None
        sessions[(adjacency.spine.node, adjacency.leaf.node)] = None
    return sessions


def check_bgp_sessions(
    compatibility: Sequence[AnswerRow],
    status: Sequence[AnswerRow],
    expected: ExpectedState,
) -> AssuranceSection:
    """Compare configured and predicted sessions with expected adjacencies."""
    expected_pairs = _expected_directed_sessions(expected)
    findings: list[AssuranceFinding] = []
    compatible: dict[tuple[str, str], str] = {}
    for row in compatibility:
        pair = (_text(row, "Node"), _text(row, "Remote_Node"))
        compatible[pair] = _text(row, "Configured_Status")
        if pair not in expected_pairs:
            findings.append(
                AssuranceFinding(
                    rule_id="BFA004",
                    category=AssuranceCategory.BGP,
                    target=f"{pair[0]}->{pair[1]}",
                    message="unexpected BGP session is configured",
                    hint="Remove the neighbor or add it to the authoritative topology.",
                )
            )
    established: dict[tuple[str, str], str] = {
        (_text(row, "Node"), _text(row, "Remote_Node")): _text(row, "Established_Status")
        for row in status
    }

    session_passed: dict[tuple[str, str], bool] = {}
    for pair in expected_pairs:
        target = f"{pair[0]}->{pair[1]}"
        session_passed[pair] = True
        configured = compatible.get(pair)
        if configured != "UNIQUE_MATCH":
            session_passed[pair] = False
            findings.append(
                AssuranceFinding(
                    rule_id="BFA003",
                    category=AssuranceCategory.BGP,
                    target=target,
                    message=(
                        "expected BGP session is not uniquely configured"
                        + (f" (status {configured})" if configured else "")
                    ),
                    hint="Check rendered neighbor addresses and remote AS numbers.",
                )
            )
            continue
        predicted = established.get(pair)
        if predicted != "ESTABLISHED":
            session_passed[pair] = False
            findings.append(
                AssuranceFinding(
                    rule_id="BFA005",
                    category=AssuranceCategory.BGP,
                    target=target,
                    message=(
                        "session is not predicted to establish"
                        + (f" (status {predicted})" if predicted else "")
                    ),
                    hint="Inspect addressing, AS numbers, and interface configuration.",
                )
            )
    return AssuranceSection(
        name="bgp-sessions",
        expected=len(expected_pairs),
        passed=sum(session_passed.values()),
        findings=tuple(findings),
    )


def check_loops(loops: Sequence[AnswerRow]) -> AssuranceSection:
    """Require an empty forwarding-loop answer."""
    findings = tuple(
        AssuranceFinding(
            rule_id="BFA006",
            category=AssuranceCategory.FORWARDING,
            target=str(row.get("Flow", "<unknown flow>")),
            message="a forwarding loop is derivable from the generated configuration",
            hint="Inspect route advertisements and next-hop resolution for this flow.",
        )
        for row in loops
    )
    return AssuranceSection(
        name="forwarding-loops",
        expected=1,
        passed=0 if findings else 1,
        findings=findings,
    )


def _bgp_route_index(routes: Sequence[AnswerRow]) -> dict[tuple[str, str], set[str]]:
    index: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for row in routes:
        key = (_text(row, "Node"), _text(row, "Network"))
        next_hop = _text(row, "Next_Hop_IP")
        if next_hop:
            index[key].add(next_hop)
    return dict(index)


def check_derived_routes(routes: Sequence[AnswerRow], expected: ExpectedState) -> AssuranceSection:
    """Require the derived RIB to carry expected BGP prefixes and ECMP width."""
    index = _bgp_route_index(routes)
    findings: list[AssuranceFinding] = []
    expectations = [item for item in expected.router_prefixes if item.protocol == "bgp"]
    passed = 0
    for expectation in expectations:
        target = f"{expectation.router}:{expectation.prefix}"
        next_hops = index.get((expectation.router, str(expectation.prefix)))
        if next_hops is None:
            findings.append(
                AssuranceFinding(
                    rule_id="BFA007",
                    category=AssuranceCategory.ROUTES,
                    target=target,
                    message="expected BGP prefix is absent from the derived RIB",
                    hint="Inspect advertised networks and session predictions.",
                )
            )
            continue
        if len(next_hops) < expectation.min_next_hops:
            findings.append(
                AssuranceFinding(
                    rule_id="BFA007",
                    category=AssuranceCategory.ROUTES,
                    target=target,
                    message=(
                        f"derived RIB has {len(next_hops)} next hop(s), "
                        f"expected at least {expectation.min_next_hops}"
                    ),
                    hint="Inspect multipath configuration and redundant uplinks.",
                )
            )
            continue
        passed += 1
    return AssuranceSection(
        name="derived-routes",
        expected=len(expectations),
        passed=passed,
        findings=tuple(findings),
    )


def check_isolation(routes: Sequence[AnswerRow], expected: ExpectedState) -> AssuranceSection:
    """Reject derived BGP routes that leak between plane address pools."""
    router_planes: dict[str, FabricPlane] = {
        item.router: item.plane for item in expected.router_prefixes
    }
    forbidden_by_plane: dict[FabricPlane, tuple[IPv4Network, ...]] = {
        contract.source_plane: contract.forbidden_route_pools for contract in expected.isolation
    }
    findings: list[AssuranceFinding] = []
    failed_planes: set[FabricPlane] = set()
    for row in routes:
        node = _text(row, "Node")
        plane = router_planes.get(node)
        if plane is None:
            continue
        forbidden = forbidden_by_plane.get(plane, ())
        network_text = _text(row, "Network")
        if not network_text:
            continue
        network = IPv4Network(network_text)
        pool = next((pool for pool in forbidden if network.overlaps(pool)), None)
        if pool is not None:
            failed_planes.add(plane)
            findings.append(
                AssuranceFinding(
                    rule_id="BFA008",
                    category=AssuranceCategory.ISOLATION,
                    target=f"{node}:{network}",
                    message=f"derived route overlaps forbidden cross-plane pool {pool}",
                    hint="Remove route leaking between Plane A and Plane B.",
                )
            )
    return AssuranceSection(
        name="cross-plane-isolation",
        expected=len(forbidden_by_plane),
        passed=len(forbidden_by_plane) - len(failed_planes),
        findings=tuple(findings),
    )
