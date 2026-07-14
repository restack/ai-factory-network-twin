import json
import os
from pathlib import Path

import pytest

from aftwin.compiler.compiler import compile_fabric, load_platform_map
from aftwin.netbox.fixture import fixture_to_fabric, load_fixture
from aftwin.policy.engine import PolicyEngine
from aftwin.policy.profile import load_policy_profile
from aftwin.runtime.containerlab import Containerlab
from aftwin.runtime.executor import SubprocessExecutor
from aftwin.runtime.images import DockerImagePreflight
from aftwin.runtime.lifecycle import LabLifecycle
from aftwin.verify.verifier import RuntimeVerifier

pytestmark = pytest.mark.containerlab


@pytest.mark.skipif(
    os.getenv("AFTWIN_RUN_SRLINUX_INTEGRATION") != "1",
    reason="set AFTWIN_RUN_SRLINUX_INTEGRATION=1 for privileged SR Linux lab tests",
)
def test_srlinux_golden_lab_deploy_verify_and_destroy(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(Path("fixtures/mini-dual-plane-srlinux.yaml")))
    profile = load_policy_profile(Path("config/policies/mini-dual-plane-srlinux.yaml"))
    site_dir = tmp_path / "mini-dual-plane-srlinux"
    report = PolicyEngine().validate(fabric, profile)
    reports = site_dir / "reports"
    reports.mkdir(parents=True)
    (reports / "static-validation.json").write_text(report.to_json(), encoding="utf-8")
    compile_fabric(
        fabric, load_platform_map(Path("config/platform-map-srlinux.yaml")), profile, site_dir
    )
    assert json.loads((reports / "static-validation.json").read_text())["passed"] is True

    containerlab = Containerlab(SubprocessExecutor())
    lifecycle = LabLifecycle(
        containerlab,
        image_preflight=DockerImagePreflight(SubprocessExecutor()),
    )
    try:
        deployed = lifecycle.deploy(site_dir)
        assert deployed.inspection.running
        # SR Linux nodes boot slower than plain containers; allow full NOS
        # readiness plus BGP convergence before evidence collection fails.
        verification = RuntimeVerifier(containerlab, convergence_timeout_seconds=180.0).verify(
            site_dir
        )
        assert verification.passed, verification.render_human()
    finally:
        destroyed = lifecycle.destroy(site_dir)
        assert not destroyed.inspection.running
