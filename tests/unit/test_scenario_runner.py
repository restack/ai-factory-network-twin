import json
from collections.abc import Sequence
from pathlib import Path

from aftwin.compiler.manifest import BuildManifest
from aftwin.domain.enums import FabricPlane
from aftwin.errors import RuntimeVerificationError
from aftwin.runtime.executor import CommandResult
from aftwin.scenario.models import load_scenario
from aftwin.scenario.runner import ScenarioRunner
from aftwin.verify.report import VerificationReport, VerificationSection


def _result(node: str, command: Sequence[str], return_code: int, stdout: object) -> CommandResult:
    payload = {
        f"clab-mini-{node}": [
            {
                "cmd": list(command),
                "return-code": return_code,
                "stdout": stdout,
                "stderr": "",
            }
        ]
    }
    return CommandResult(("containerlab", "exec"), 0, json.dumps(payload), "", 0.01)


class FakeRuntime:
    def __init__(self, *, fail_restore: bool = False) -> None:
        self.states: dict[tuple[str, str], bool] = {}
        self.fail_restore = fail_restore
        self.actions: list[tuple[str, str, str]] = []

    def exec(self, topology: Path, node: str, command: Sequence[str]) -> CommandResult:
        del topology
        if tuple(command[:4]) == ("ip", "link", "set", "dev"):
            interface = command[4]
            state = command[5]
            self.actions.append((node, interface, state))
            if state == "up" and self.fail_restore:
                return _result(node, command, 2, "restore failed")
            self.states[(node, interface)] = state == "up"
            return _result(node, command, 0, "")
        interface = command[-1]
        flags = ["UP"] if self.states.get((node, interface), True) else []
        return _result(node, command, 0, [{"ifname": interface, "flags": flags}])

    def deploy(self, topology: Path, *, reconfigure: bool = False) -> CommandResult:
        raise AssertionError((topology, reconfigure))

    def destroy(self, topology: Path, *, cleanup: bool = True) -> CommandResult:
        raise AssertionError((topology, cleanup))

    def inspect(self, topology: Path) -> CommandResult:
        raise AssertionError(topology)

    def inspect_all(self) -> CommandResult:
        raise AssertionError("not used")


class FakeVerifier:
    def __init__(self, *, connectivity_error: bool = False) -> None:
        self.connectivity_error = connectivity_error
        self.full_calls = 0

    def verify(self, site_dir: Path) -> VerificationReport:
        del site_dir
        self.full_calls += 1
        return VerificationReport(
            sections=(VerificationSection(name="full", expected=4, passed=4),)
        )

    def verify_connectivity(self, site_dir: Path) -> tuple[VerificationSection, ...]:
        del site_dir
        if self.connectivity_error:
            raise RuntimeVerificationError("ping collection failed")
        return (
            VerificationSection(name="cross-plane-isolation", expected=1, passed=1),
            VerificationSection(name="reachability-plane-a", expected=1, passed=1),
            VerificationSection(name="reachability-plane-b", expected=1, passed=1),
        )

    def reachability_contract(self, site_dir: Path) -> frozenset[tuple[FabricPlane, str, str]]:
        del site_dir
        return frozenset(
            {
                (FabricPlane.A, "gpu01", "gpu03"),
                (FabricPlane.B, "gpu01", "gpu03"),
            }
        )


def _site_dir(tmp_path: Path) -> Path:
    site_dir = tmp_path / "mini"
    site_dir.mkdir()
    (site_dir / "topology.clab.yml").write_text(
        """name: mini
topology:
  nodes:
    leaf-a1: {}
    spine-a1: {}
  links:
    - endpoints: [leaf-a1:eth1, spine-a1:eth1]
    - endpoints: [leaf-a2:eth1, spine-a1:eth2]
""",
        encoding="utf-8",
    )
    BuildManifest(
        compiler_version="unit-test",
        source_revision="c" * 64,
        build_hash="b" * 64,
        files=(),
    ).write(site_dir)
    return site_dir


def test_link_failure_runs_four_phases_and_restores(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    verifier = FakeVerifier()
    scenario = load_scenario(Path("scenarios/link-failure.yaml"))
    site_dir = _site_dir(tmp_path)

    report = ScenarioRunner(runtime, verifier).run(site_dir, scenario)

    assert report.passed
    assert report.build_hash == "b" * 64
    assert report.source_revision == "c" * 64
    assert len(report.scenario_revision) == 64
    assert runtime.actions == [("leaf-a1", "eth1", "down"), ("leaf-a1", "eth1", "up")]
    assert verifier.full_calls == 2
    assert (site_dir / "reports" / "scenarios" / f"{scenario.name}.json").is_file()


def test_spine_failure_derives_all_links_and_restores_in_reverse(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    scenario = load_scenario(Path("scenarios/spine-failure.yaml"))

    report = ScenarioRunner(runtime, FakeVerifier()).run(_site_dir(tmp_path), scenario)

    assert report.passed
    assert report.target.interfaces == ("eth1", "eth2")
    assert runtime.actions == [
        ("spine-a1", "eth1", "down"),
        ("spine-a1", "eth2", "down"),
        ("spine-a1", "eth2", "up"),
        ("spine-a1", "eth1", "up"),
    ]


def test_collection_failure_still_restores_and_is_reported(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    scenario = load_scenario(Path("scenarios/link-failure.yaml"))

    report = ScenarioRunner(runtime, FakeVerifier(connectivity_error=True)).run(
        _site_dir(tmp_path), scenario
    )

    assert not report.passed
    assert report.restored
    assert {finding.rule_id for finding in report.findings} == {"SCN004"}
    assert runtime.actions[-1] == ("leaf-a1", "eth1", "up")


def test_restore_failure_is_actionable_and_skips_recovery(tmp_path: Path) -> None:
    runtime = FakeRuntime(fail_restore=True)
    scenario = load_scenario(Path("scenarios/link-failure.yaml"))

    report = ScenarioRunner(runtime, FakeVerifier()).run(_site_dir(tmp_path), scenario)

    assert not report.passed
    assert not report.restored
    assert {finding.rule_id for finding in report.findings} == {"SCN005", "SCN007"}


def test_unknown_declared_probe_is_rejected_before_fault_injection(tmp_path: Path) -> None:
    runtime = FakeRuntime()
    scenario = load_scenario(Path("scenarios/link-failure.yaml"))
    unknown = scenario.expected.probes[0].model_copy(update={"destination_node": "gpu99"})
    scenario = scenario.model_copy(
        update={
            "expected": scenario.expected.model_copy(
                update={"probes": (unknown, scenario.expected.probes[1])}
            )
        }
    )

    try:
        ScenarioRunner(runtime, FakeVerifier()).run(_site_dir(tmp_path), scenario)
    except RuntimeVerificationError as error:
        assert "absent from generated expected state" in error.message
    else:
        raise AssertionError("unknown scenario probe unexpectedly passed")
    assert runtime.actions == []
