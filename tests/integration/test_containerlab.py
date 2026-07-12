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
from aftwin.runtime.lifecycle import LabLifecycle
from aftwin.scenario.models import load_scenario
from aftwin.scenario.runner import ScenarioRunner
from aftwin.verify.verifier import RuntimeVerifier

pytestmark = pytest.mark.containerlab


@pytest.mark.skipif(
    os.getenv("AFTWIN_RUN_CONTAINERLAB_INTEGRATION") != "1",
    reason="set AFTWIN_RUN_CONTAINERLAB_INTEGRATION=1 for privileged local lab tests",
)
def test_golden_lab_deploy_verify_and_destroy(tmp_path: Path) -> None:
    fabric = fixture_to_fabric(load_fixture(Path("fixtures/mini-dual-plane.yaml")))
    profile = load_policy_profile(Path("config/policies/mini-dual-plane.yaml"))
    site_dir = tmp_path / "mini-dual-plane"
    report = PolicyEngine().validate(fabric, profile)
    reports = site_dir / "reports"
    reports.mkdir(parents=True)
    (reports / "static-validation.json").write_text(report.to_json(), encoding="utf-8")
    compile_fabric(fabric, load_platform_map(Path("config/platform-map.yaml")), profile, site_dir)
    assert json.loads((reports / "static-validation.json").read_text())["passed"] is True

    containerlab = Containerlab(SubprocessExecutor())
    lifecycle = LabLifecycle(containerlab)
    try:
        deployed = lifecycle.deploy(site_dir)
        assert deployed.inspection.running
        verification = RuntimeVerifier(containerlab).verify(site_dir)
        assert verification.passed, verification.render_human()
        runner = ScenarioRunner(containerlab, RuntimeVerifier(containerlab))
        for scenario_path in (
            Path("scenarios/link-failure.yaml"),
            Path("scenarios/spine-failure.yaml"),
        ):
            scenario = runner.run(site_dir, load_scenario(scenario_path))
            assert scenario.passed, scenario.render_human()
    finally:
        destroyed = lifecycle.destroy(site_dir)
        assert not destroyed.inspection.running
