import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from aftwin.compiler.manifest import BuildManifest
from aftwin.runtime.executor import (
    CommandExecutionError,
    CommandFailureKind,
    CommandResult,
)
from aftwin.runtime.images import DockerImagePreflight
from aftwin.runtime.lifecycle import LabLifecycle, LabLifecycleError


class FakeExecutor:
    """Answer docker probes from a scripted availability table."""

    def __init__(
        self,
        *,
        local: set[str] | None = None,
        pullable: set[str] | None = None,
        error: CommandExecutionError | None = None,
    ) -> None:
        self.local = local or set()
        self.pullable = pullable or set()
        self.error = error
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv: Sequence[str], *, timeout_seconds: float | None = None) -> CommandResult:
        command = tuple(argv)
        self.calls.append(command)
        if self.error is not None:
            raise self.error
        if command[:3] == ("docker", "image", "inspect"):
            available = command[3] in self.local
        elif command[:2] == ("docker", "pull"):
            available = command[2] in self.pullable
        else:
            raise AssertionError(f"unexpected docker command: {command}")
        if not available:
            raise CommandExecutionError(
                kind=CommandFailureKind.NON_ZERO_EXIT,
                argv=command,
                message="runtime command exited with status 1",
                timeout_seconds=timeout_seconds or 0.0,
                returncode=1,
                stderr="No such image",
            )
        return CommandResult(command, 0, "", "", 0.1)


def test_locally_present_images_are_not_pulled() -> None:
    executor = FakeExecutor(local={"aftwin-endpoint:0.1.0"})

    missing = DockerImagePreflight(executor).missing_images(["aftwin-endpoint:0.1.0"])

    assert missing == ()
    assert all(call[:2] != ("docker", "pull") for call in executor.calls)


def test_missing_local_image_falls_back_to_one_pull() -> None:
    executor = FakeExecutor(pullable={"ghcr.io/nokia/srlinux:24.10.1"})

    missing = DockerImagePreflight(executor).missing_images(
        ["ghcr.io/nokia/srlinux:24.10.1", "ghcr.io/nokia/srlinux:24.10.1"]
    )

    assert missing == ()
    assert executor.calls.count(("docker", "pull", "ghcr.io/nokia/srlinux:24.10.1")) == 1


def test_unavailable_images_are_reported_in_input_order() -> None:
    executor = FakeExecutor(local={"quay.io/frrouting/frr:10.3.4"})

    missing = DockerImagePreflight(executor).missing_images(
        ["aftwin-endpoint:0.1.0", "quay.io/frrouting/frr:10.3.4", "ghcr.io/vendor/nos:1.0.0"]
    )

    assert missing == ("aftwin-endpoint:0.1.0", "ghcr.io/vendor/nos:1.0.0")


def test_pull_can_be_disabled() -> None:
    executor = FakeExecutor(pullable={"ghcr.io/nokia/srlinux:24.10.1"})

    missing = DockerImagePreflight(executor, pull_missing=False).missing_images(
        ["ghcr.io/nokia/srlinux:24.10.1"]
    )

    assert missing == ("ghcr.io/nokia/srlinux:24.10.1",)
    assert all(call[:2] != ("docker", "pull") for call in executor.calls)


def test_docker_infrastructure_failures_propagate() -> None:
    executor = FakeExecutor(
        error=CommandExecutionError(
            kind=CommandFailureKind.NOT_FOUND,
            argv=("docker",),
            message="runtime executable was not found: docker",
            timeout_seconds=30.0,
        )
    )

    with pytest.raises(CommandExecutionError, match="not found"):
        DockerImagePreflight(executor).missing_images(["aftwin-endpoint:0.1.0"])


class FakeImagePreflight:
    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        self.requested: list[tuple[str, ...]] = []

    def missing_images(self, images: Sequence[str]) -> tuple[str, ...]:
        self.requested.append(tuple(images))
        return self.missing


class FakeContainerlab:
    def __init__(self, inspections: list[object]) -> None:
        self.inspections = list(inspections)
        self.calls: list[tuple[object, ...]] = []

    def deploy(self, topology: Path, *, reconfigure: bool = False) -> CommandResult:
        self.calls.append(("deploy", topology, reconfigure))
        return CommandResult(("containerlab",), 0, "", "", 0.1)

    def destroy(self, topology: Path, *, cleanup: bool = True) -> CommandResult:
        self.calls.append(("destroy", topology, cleanup))
        return CommandResult(("containerlab",), 0, "", "", 0.1)

    def inspect(self, topology: Path) -> CommandResult:
        raise AssertionError("lifecycle must use global inspection")

    def inspect_all(self) -> CommandResult:
        self.calls.append(("inspect_all",))
        return CommandResult(("containerlab",), 0, json.dumps(self.inspections.pop(0)), "", 0.1)

    def exec(self, topology: Path, node: str, command: Sequence[str]) -> CommandResult:
        raise AssertionError("deploy preflight must not exec into nodes")


def _build_dir(tmp_path: Path) -> Path:
    site_dir = tmp_path / "aif-lab"
    (site_dir / "reports").mkdir(parents=True)
    (site_dir / "topology.clab.yml").write_text(
        "name: lab\n"
        "topology:\n"
        "  nodes:\n"
        "    leaf-a1: {image: quay.io/frrouting/frr:10.3.4}\n"
        "    gpu01: {image: aftwin-endpoint:0.1.0}\n",
        encoding="utf-8",
    )
    (site_dir / "reports" / "static-validation.json").write_text(
        json.dumps({"passed": True}), encoding="utf-8"
    )
    (site_dir / "inventory.json").write_text(json.dumps({"node_count": 2}), encoding="utf-8")
    (site_dir / "expected-state.json").write_text("{}", encoding="utf-8")
    BuildManifest.create(site_dir, source_revision="unit-test").write(site_dir)
    return site_dir


def test_deploy_fails_before_containerlab_when_images_are_unavailable(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    runtime = FakeContainerlab([{}])
    preflight = FakeImagePreflight(missing=("aftwin-endpoint:0.1.0",))

    with pytest.raises(LabLifecycleError, match="images are unavailable") as caught:
        LabLifecycle(runtime, image_preflight=preflight).deploy(site_dir)

    assert caught.value.details["missing_images"] == ["aftwin-endpoint:0.1.0"]
    assert "hint" in caught.value.details
    assert preflight.requested == [("aftwin-endpoint:0.1.0", "quay.io/frrouting/frr:10.3.4")]
    assert all(call[0] != "deploy" for call in runtime.calls)


def test_deploy_proceeds_when_every_image_is_available(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)
    runtime = FakeContainerlab(
        [
            {},
            {
                "lab": [
                    {"name": "clab-lab-gpu01", "state": "running"},
                    {"name": "clab-lab-leaf-a1", "state": "running"},
                ]
            },
        ]
    )
    preflight = FakeImagePreflight(missing=())

    result = LabLifecycle(runtime, image_preflight=preflight).deploy(site_dir)

    assert result.changed
    assert preflight.requested == [("aftwin-endpoint:0.1.0", "quay.io/frrouting/frr:10.3.4")]
    assert any(call[0] == "deploy" for call in runtime.calls)


def test_required_images_are_unique_and_sorted(tmp_path: Path) -> None:
    site_dir = _build_dir(tmp_path)

    images = LabLifecycle.required_images(site_dir / "topology.clab.yml")

    assert images == ("aftwin-endpoint:0.1.0", "quay.io/frrouting/frr:10.3.4")
