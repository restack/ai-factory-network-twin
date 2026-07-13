"""Reversible M5 failure injection and recovery orchestration."""

import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, cast

import yaml
from pydantic import ValidationError

from aftwin.domain.enums import FabricPlane
from aftwin.errors import RuntimeVerificationError
from aftwin.runtime.executor import CommandExecutionError
from aftwin.runtime.lifecycle import ContainerlabRuntime, LabLifecycle, LabLifecycleError
from aftwin.scenario.models import FailureScenario, FailureTarget, ScenarioType
from aftwin.scenario.report import (
    ScenarioFinding,
    ScenarioPhase,
    ScenarioPhaseState,
    ScenarioReport,
)
from aftwin.verify.report import VerificationReport, VerificationSection
from aftwin.verify.verifier import NodeCommandResult, decode_node_command


class ScenarioVerificationService(Protocol):
    """Runtime checks consumed by the scenario runner."""

    def verify(self, site_dir: Path) -> VerificationReport: ...

    def verify_connectivity(self, site_dir: Path) -> tuple[VerificationSection, ...]: ...

    def reachability_contract(self, site_dir: Path) -> frozenset[tuple[FabricPlane, str, str]]: ...


def _scenario_finding(rule_id: str, target: str, cause: str, hint: str) -> ScenarioFinding:
    return ScenarioFinding(rule_id=rule_id, target=target, cause=cause, hint=hint)


def _state_from_sections(
    phase: ScenarioPhase,
    sections: Sequence[VerificationSection],
    *,
    extra_expected: int = 0,
    extra_passed: int = 0,
    extra_findings: Sequence[ScenarioFinding] = (),
) -> ScenarioPhaseState:
    findings = list(extra_findings)
    for section in sections:
        findings.extend(
            _scenario_finding(finding.rule_id, finding.target, finding.message, finding.hint)
            for finding in section.findings
        )
    return ScenarioPhaseState(
        phase=phase,
        expected_probes=sum(section.expected for section in sections) + extra_expected,
        passed_probes=sum(section.passed for section in sections) + extra_passed,
        findings=tuple(findings),
    )


class ScenarioRunner:
    """Apply one bounded fault, prove survival, and always restore it."""

    def __init__(
        self,
        containerlab: ContainerlabRuntime,
        verifier: ScenarioVerificationService,
        *,
        survival_timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        if survival_timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("scenario timeouts must be positive")
        self._containerlab = containerlab
        self._verifier = verifier
        self._survival_timeout_seconds = survival_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    def run(self, site_dir: Path, scenario: FailureScenario) -> ScenarioReport:
        """Run a scenario and persist deterministic four-phase evidence."""
        try:
            scenario = FailureScenario.model_validate(scenario.model_dump(mode="python"))
        except ValidationError as error:
            raise RuntimeVerificationError(
                "failure scenario contains unsafe identifiers"
            ) from error
        try:
            deployment = LabLifecycle(self._containerlab).require_deployed_build(site_dir)
        except LabLifecycleError as error:
            raise RuntimeVerificationError(error.message, details=error.details) from error
        topology = site_dir / "topology.clab.yml"
        interfaces = self._target_interfaces(topology, scenario)
        self._validate_expectations(site_dir, scenario)
        baseline = self._verifier.verify(site_dir)
        before = _state_from_sections(ScenarioPhase.BEFORE, baseline.sections)
        if not before.successful:
            raise RuntimeVerificationError(
                "scenario baseline is unhealthy; refusing to inject a fault",
                details={"scenario": scenario.name},
            )

        injection_findings: list[ScenarioFinding] = []
        fault_active = 0
        restored_interfaces = 0
        restore_findings: list[ScenarioFinding] = []
        connectivity: tuple[VerificationSection, ...] = ()
        try:
            for interface in interfaces:
                try:
                    self._set_interface(topology, scenario.failure.target.node, interface, up=False)
                    if not self._interface_is_up(topology, scenario.failure.target.node, interface):
                        fault_active += 1
                    else:
                        injection_findings.append(
                            _scenario_finding(
                                "SCN003",
                                f"{scenario.failure.target.node}:{interface}",
                                "fault target remained administratively up",
                                "Inspect the runtime interface and Containerlab exec permissions.",
                            )
                        )
                except RuntimeVerificationError as error:
                    injection_findings.append(
                        _scenario_finding(
                            "SCN002",
                            f"{scenario.failure.target.node}:{interface}",
                            str(error),
                            "Restore the target interface and inspect runtime command evidence.",
                        )
                    )
            if fault_active == len(interfaces):
                try:
                    connectivity = self._wait_for_survival(site_dir, scenario)
                except RuntimeVerificationError as error:
                    injection_findings.append(
                        _scenario_finding(
                            "SCN004",
                            scenario.name,
                            str(error),
                            "Inspect alternate paths and rerun the failure scenario.",
                        )
                    )
        finally:
            for interface in reversed(interfaces):
                try:
                    self._set_interface(topology, scenario.failure.target.node, interface, up=True)
                    if self._interface_is_up(topology, scenario.failure.target.node, interface):
                        restored_interfaces += 1
                    else:
                        restore_findings.append(
                            _scenario_finding(
                                "SCN006",
                                f"{scenario.failure.target.node}:{interface}",
                                "restored interface is not administratively up",
                                "Set the interface up manually before reusing the lab.",
                            )
                        )
                except RuntimeVerificationError as error:
                    restore_findings.append(
                        _scenario_finding(
                            "SCN005",
                            f"{scenario.failure.target.node}:{interface}",
                            str(error),
                            "Set the interface up manually and rerun full verification.",
                        )
                    )

        during = _state_from_sections(
            ScenarioPhase.DURING,
            connectivity,
            extra_expected=len(interfaces),
            extra_passed=fault_active,
            extra_findings=injection_findings,
        )
        after = ScenarioPhaseState(
            phase=ScenarioPhase.AFTER,
            expected_probes=len(interfaces),
            passed_probes=restored_interfaces,
            findings=tuple(restore_findings),
        )
        restored = after.successful
        recovery = self._recovery_state(site_dir, restored)
        report = ScenarioReport(
            scenario=scenario.name,
            scenario_revision=scenario.revision,
            build_hash=deployment.build_hash,
            source_revision=deployment.source_revision,
            failure_type=scenario.failure.type,
            target=FailureTarget(node=scenario.failure.target.node, interfaces=interfaces),
            restored=restored,
            states=(before, during, after, recovery),
        )
        report_path = site_dir / "reports" / "scenarios" / f"{scenario.name}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report.to_json(), encoding="utf-8", newline="\n")
        return report

    def _wait_for_survival(
        self, site_dir: Path, scenario: FailureScenario
    ) -> tuple[VerificationSection, ...]:
        deadline = time.monotonic() + self._survival_timeout_seconds
        sections: tuple[VerificationSection, ...] = ()
        required_names = {
            *(f"reachability-plane-{plane.value}" for plane in scenario.expected.surviving_planes),
            "cross-plane-isolation",
        }
        while True:
            collected = self._verifier.verify_connectivity(site_dir)
            sections = tuple(section for section in collected if section.name in required_names)
            if {section.name for section in sections} != required_names:
                raise RuntimeVerificationError(
                    "runtime verifier did not return every scenario survival section",
                    details={"scenario": scenario.name, "required": sorted(required_names)},
                )
            if all(section.successful for section in sections) or time.monotonic() >= deadline:
                return sections
            time.sleep(self._poll_interval_seconds)

    def _validate_expectations(self, site_dir: Path, scenario: FailureScenario) -> None:
        available = self._verifier.reachability_contract(site_dir)
        requested = {
            (probe.plane, probe.source_node, probe.destination_node)
            for probe in scenario.expected.probes
        }
        missing = requested - available
        if missing:
            rendered = [
                f"{plane.value}:{source}->{destination}"
                for plane, source, destination in sorted(
                    missing, key=lambda item: (item[0].value, item[1], item[2])
                )
            ]
            raise RuntimeVerificationError(
                "scenario expects reachability probes absent from generated expected state",
                details={"scenario": scenario.name, "missing_probes": rendered},
            )

    def _recovery_state(self, site_dir: Path, restored: bool) -> ScenarioPhaseState:
        if not restored:
            finding = _scenario_finding(
                "SCN007",
                site_dir.name,
                "full recovery verification was skipped because restoration failed",
                "Repair every target interface and run aftwin verify.",
            )
            return ScenarioPhaseState(
                phase=ScenarioPhase.RECOVERY,
                expected_probes=1,
                passed_probes=0,
                findings=(finding,),
            )
        try:
            report = self._verifier.verify(site_dir)
        except RuntimeVerificationError as error:
            finding = _scenario_finding(
                "SCN007",
                site_dir.name,
                str(error),
                "Inspect BGP and route convergence, then rerun full verification.",
            )
            return ScenarioPhaseState(
                phase=ScenarioPhase.RECOVERY,
                expected_probes=1,
                passed_probes=0,
                findings=(finding,),
            )
        return _state_from_sections(ScenarioPhase.RECOVERY, report.sections)

    def _set_interface(self, topology: Path, node: str, interface: str, *, up: bool) -> None:
        state = "up" if up else "down"
        result = self._exec(topology, node, ("ip", "link", "set", "dev", interface, state))
        if result.return_code != 0:
            raise RuntimeVerificationError(
                f"failed to set {node}:{interface} {state}",
                details={"node": node, "interface": interface, "return_code": result.return_code},
            )

    def _interface_is_up(self, topology: Path, node: str, interface: str) -> bool:
        result = self._exec(topology, node, ("ip", "-j", "link", "show", "dev", interface))
        if result.return_code != 0:
            raise RuntimeVerificationError(
                f"failed to inspect {node}:{interface}",
                details={"node": node, "interface": interface},
            )
        payload = result.stdout
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as error:
                raise RuntimeVerificationError(
                    f"interface state is invalid for {node}:{interface}"
                ) from error
        if not isinstance(payload, list):
            raise RuntimeVerificationError(f"interface state is invalid for {node}:{interface}")
        payload_list = cast(list[object], payload)
        if len(payload_list) != 1 or not isinstance(payload_list[0], dict):
            raise RuntimeVerificationError(f"interface state is invalid for {node}:{interface}")
        flags = cast(dict[str, object], payload_list[0]).get("flags", [])
        return isinstance(flags, list) and "UP" in flags

    def _exec(self, topology: Path, node: str, command: Sequence[str]) -> NodeCommandResult:
        try:
            result = self._containerlab.exec(topology, node, command)
        except CommandExecutionError as error:
            raise RuntimeVerificationError(
                f"scenario runtime command failed for {node}: {error}",
                details={"node": node, "command": error.as_dict()},
            ) from error
        return decode_node_command(result, node)

    @staticmethod
    def _target_interfaces(topology: Path, scenario: FailureScenario) -> tuple[str, ...]:
        if scenario.failure.type is ScenarioType.LINK_DOWN:
            return scenario.failure.target.interfaces
        try:
            document: object = yaml.safe_load(topology.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise RuntimeVerificationError(
                f"topology is unreadable or invalid: {topology}"
            ) from error
        if not isinstance(document, dict):
            raise RuntimeVerificationError("topology is not a YAML object")
        topology_data = cast(dict[str, object], document).get("topology")
        if not isinstance(topology_data, dict):
            raise RuntimeVerificationError("topology has no link list")
        links = cast(dict[str, object], topology_data).get("links")
        if not isinstance(links, list):
            raise RuntimeVerificationError("topology has no link list")
        prefix = f"{scenario.failure.target.node}:"
        interfaces = {
            endpoint.removeprefix(prefix)
            for link in cast(list[object], links)
            if isinstance(link, dict)
            for endpoints in [cast(dict[str, object], link).get("endpoints")]
            if isinstance(endpoints, list)
            for endpoint in cast(list[object], endpoints)
            if isinstance(endpoint, str) and endpoint.startswith(prefix)
        }
        if not interfaces:
            raise RuntimeVerificationError(
                f"scenario target has no fabric interfaces: {scenario.failure.target.node}"
            )
        return tuple(sorted(interfaces))
