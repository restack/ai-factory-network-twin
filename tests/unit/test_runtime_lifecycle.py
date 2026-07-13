import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from aftwin.compiler.manifest import BuildManifest
from aftwin.errors import ExitCode
from aftwin.runtime.executor import (
    CommandExecutionError,
    CommandFailureKind,
    CommandResult,
)
from aftwin.runtime.lifecycle import (
    DEPLOYMENT_STAMP_PATH,
    DeploymentStamp,
    LabInspection,
    LabLifecycle,
    LabLifecycleError,
)


def _result(stdout: str = "") -> CommandResult:
    return CommandResult(("containerlab",), 0, stdout, "", 0.1)


class FakeContainerlab:
    def __init__(self, inspections: list[object | CommandExecutionError]) -> None:
        self.inspections = list(inspections)
        self.calls: list[tuple[object, ...]] = []
        self.deploy_error: CommandExecutionError | None = None

    def deploy(self, topology: Path, *, reconfigure: bool = False) -> CommandResult:
        self.calls.append(("deploy", topology, reconfigure))
        if self.deploy_error is not None:
            raise self.deploy_error
        return _result()

    def destroy(self, topology: Path, *, cleanup: bool = True) -> CommandResult:
        self.calls.append(("destroy", topology, cleanup))
        return _result()

    def inspect(self, topology: Path) -> CommandResult:
        self.calls.append(("inspect", topology))
        raise AssertionError("lifecycle must use global inspection for partial-lab safety")

    def inspect_all(self) -> CommandResult:
        self.calls.append(("inspect_all",))
        inspection = self.inspections.pop(0)
        if isinstance(inspection, CommandExecutionError):
            raise inspection
        return _result(json.dumps(inspection))

    def exec(self, topology: Path, node: str, command: Sequence[str]) -> CommandResult:
        self.calls.append(("exec", topology, node, tuple(command)))
        return _result()


def _build_dir(tmp_path: Path, *, passed: bool = True) -> Path:
    site_dir = tmp_path / "aif-lab"
    (site_dir / "reports").mkdir(parents=True)
    (site_dir / "topology.clab.yml").write_text(
        "name: lab\ntopology:\n  nodes:\n    leaf-a1: {}\n", encoding="utf-8"
    )
    (site_dir / "reports" / "static-validation.json").write_text(
        json.dumps({"passed": passed}), encoding="utf-8"
    )
    (site_dir / "inventory.json").write_text(json.dumps({"node_count": 1}), encoding="utf-8")
    (site_dir / "expected-state.json").write_text("{}", encoding="utf-8")
    BuildManifest.create(site_dir, source_revision="unit-test").write(site_dir)
    return site_dir


def test_deploy_requires_validation_then_proves_lab_is_running(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    runtime = FakeContainerlab([{}, {"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}])

    result = LabLifecycle(runtime).deploy(site_dir)

    topology = site_dir / "topology.clab.yml"
    assert result.changed
    assert result.inspection.running
    stamp = DeploymentStamp.model_validate_json(
        (site_dir / DEPLOYMENT_STAMP_PATH).read_text(encoding="utf-8")
    )
    assert stamp.lab_name == "lab"
    assert stamp.container_names == ("clab-lab-leaf-a1",)
    assert runtime.calls == [
        ("inspect_all",),
        ("deploy", topology, False),
        ("inspect_all",),
    ]


def test_missing_lab_inspection_is_an_empty_runtime_state(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    missing = CommandExecutionError(
        kind=CommandFailureKind.NON_ZERO_EXIT,
        argv=("containerlab", "inspect"),
        message="runtime command exited with status 1",
        timeout_seconds=5,
        returncode=1,
        stderr="Lab 'mini' not found - no running containers.",
    )
    runtime = FakeContainerlab([missing])

    inspection = LabLifecycle(runtime).inspect(site_dir)

    assert not inspection.running
    assert inspection.command is None


def test_partial_lab_missing_container_message_is_not_empty_state(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    missing = CommandExecutionError(
        kind=CommandFailureKind.NON_ZERO_EXIT,
        argv=("containerlab", "inspect"),
        message="runtime command exited with status 1",
        timeout_seconds=5,
        returncode=1,
        stderr="Failed to list containers: Node clab-mini-leaf-a1. containers not found.",
    )
    runtime = FakeContainerlab([missing])

    with pytest.raises(LabLifecycleError, match="inspection failed"):
        LabLifecycle(runtime).inspect(site_dir)


def test_empty_named_inspection_is_not_running() -> None:
    inspection = LabInspection(payload={"mini": []}, command=None)

    assert not inspection.running


def test_deploy_rejects_existing_lab_without_reconfigure(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    runtime = FakeContainerlab([{"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}])

    with pytest.raises(LabLifecycleError, match="already exists") as caught:
        LabLifecycle(runtime).deploy(site_dir)

    assert caught.value.exit_code is ExitCode.DEPLOYMENT
    assert all(call[0] != "deploy" for call in runtime.calls)


def test_deploy_requires_every_inventory_node_to_be_running(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    runtime = FakeContainerlab([{}, {"lab": [{"name": "clab-lab-leaf-a1", "state": "exited"}]}])

    with pytest.raises(LabLifecycleError, match="every expected node"):
        LabLifecycle(runtime).deploy(site_dir)

    assert runtime.calls[-1][0] == "destroy"


def test_deploy_cleans_up_when_post_deploy_inspection_fails(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    inspection_error = CommandExecutionError(
        kind=CommandFailureKind.TIMED_OUT,
        argv=("containerlab", "inspect", "--all"),
        message="runtime command exceeded timeout",
        timeout_seconds=5,
    )
    runtime = FakeContainerlab([{}, inspection_error])

    with pytest.raises(LabLifecycleError, match="post-deployment inspection failed"):
        LabLifecycle(runtime).deploy(site_dir)

    assert runtime.calls[-1][0] == "destroy"


def test_deploy_refuses_failed_static_validation_before_runtime_call(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path, passed=False)
    runtime = FakeContainerlab([])

    with pytest.raises(LabLifecycleError, match="has not passed"):
        LabLifecycle(runtime).deploy(site_dir)

    assert runtime.calls == []


def test_deploy_refuses_artifacts_modified_after_compilation(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    (site_dir / "topology.clab.yml").write_text("name: tampered\n", encoding="utf-8")
    runtime = FakeContainerlab([])

    with pytest.raises(LabLifecycleError, match="differs from manifest"):
        LabLifecycle(runtime).deploy(site_dir)

    assert runtime.calls == []


def test_destroy_proves_resources_are_removed(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    DeploymentStamp.from_build(
        site_dir,
        BuildManifest.model_validate_json((site_dir / "manifest.json").read_text()),
    ).write(site_dir)
    runtime = FakeContainerlab([{"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}, {}])

    result = LabLifecycle(runtime).destroy(site_dir)

    topology = site_dir / "topology.clab.yml"
    assert result.changed
    assert not result.inspection.running
    assert not (site_dir / DEPLOYMENT_STAMP_PATH).exists()
    assert runtime.calls == [
        ("inspect_all",),
        ("destroy", topology, True),
        ("inspect_all",),
    ]


def test_destroy_is_idempotent_when_lab_is_absent(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    DeploymentStamp.from_build(
        site_dir,
        BuildManifest.model_validate_json((site_dir / "manifest.json").read_text()),
    ).write(site_dir)
    runtime = FakeContainerlab([[]])

    result = LabLifecycle(runtime).destroy(site_dir)

    assert not result.changed
    assert result.command is None
    assert not (site_dir / DEPLOYMENT_STAMP_PATH).exists()
    assert [call[0] for call in runtime.calls] == ["inspect_all"]


def test_precompile_gate_refuses_to_replace_a_running_lab_build(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    running = {"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}

    with pytest.raises(LabLifecycleError, match="destroy it before compiling"):
        LabLifecycle(FakeContainerlab([running])).require_absent_before_compile(site_dir)


def test_precompile_gate_allows_a_site_without_existing_artifacts(tmp_path: Path) -> None:
    runtime = FakeContainerlab([])

    LabLifecycle(runtime).require_absent_before_compile(tmp_path / "new-site")

    assert runtime.calls == []


def test_runtime_identity_rejects_build_b_while_build_a_is_running(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    running = {"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}
    lifecycle = LabLifecycle(FakeContainerlab([{}, running]))
    lifecycle.deploy(site_dir)

    BuildManifest.create(site_dir, source_revision="build-b").write(site_dir)

    with pytest.raises(LabLifecycleError, match="does not match the current compiled build"):
        lifecycle.require_deployed_build(site_dir)


def test_runtime_identity_rejects_artifact_tampering_before_inspection(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    running = {"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}
    runtime = FakeContainerlab([{}, running])
    lifecycle = LabLifecycle(runtime)
    lifecycle.deploy(site_dir)
    runtime.calls.clear()

    (site_dir / "inventory.json").write_text(json.dumps({"node_count": 2}), encoding="utf-8")

    with pytest.raises(LabLifecycleError, match="differs from manifest"):
        lifecycle.require_deployed_build(site_dir)
    assert runtime.calls == []


def test_runtime_identity_requires_exact_running_container_set(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    expected = {"lab": [{"name": "clab-lab-leaf-a1", "state": "running"}]}
    runtime = FakeContainerlab(
        [{}, expected, {"lab": [*expected["lab"], {"name": "clab-lab-extra", "state": "running"}]}]
    )
    lifecycle = LabLifecycle(runtime)
    lifecycle.deploy(site_dir)

    with pytest.raises(LabLifecycleError, match="container set does not match"):
        lifecycle.require_deployed_build(site_dir)


def test_command_failure_is_translated_to_structured_deployment_error(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    runtime = FakeContainerlab([[]])
    runtime.deploy_error = CommandExecutionError(
        kind=CommandFailureKind.NON_ZERO_EXIT,
        argv=("containerlab", "deploy"),
        message="runtime command exited with status 1",
        timeout_seconds=30,
        returncode=1,
        stderr="docker unavailable",
    )

    with pytest.raises(LabLifecycleError) as caught:
        LabLifecycle(runtime).deploy(site_dir)

    error = caught.value
    assert error.exit_code is ExitCode.DEPLOYMENT
    assert error.details["operation"] == "deployment"
    command = error.details["command"]
    assert isinstance(command, dict)
    assert command["kind"] == "non_zero_exit"
    assert runtime.calls[-1][0] == "destroy"
