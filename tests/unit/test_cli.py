from pathlib import Path

import pytest

from aftwin.cli import main
from aftwin.errors import ExitCode


def test_compile_requires_netbox_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)
    monkeypatch.delenv("AFTWIN_NETBOX_TOKEN", raising=False)

    with pytest.raises(SystemExit) as raised:
        main(["compile"])

    assert raised.value.code == ExitCode.CONFIGURATION
    assert "NETBOX_TOKEN is not configured" in capsys.readouterr().err


def test_compile_error_can_render_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)
    monkeypatch.delenv("AFTWIN_NETBOX_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        main(["compile", "--output", "json"])

    assert '"code": "netbox_operation_failed"' in capsys.readouterr().err


def test_validate_requires_netbox_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)
    monkeypatch.delenv("AFTWIN_NETBOX_TOKEN", raising=False)

    with pytest.raises(SystemExit) as raised:
        main(["validate"])

    assert raised.value.code == ExitCode.CONFIGURATION
    assert "NETBOX_TOKEN is not configured" in capsys.readouterr().err


def test_deploy_missing_build_uses_deployment_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AFTWIN_BUILD_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as raised:
        main(["deploy", "--site", "missing"])

    assert raised.value.code == ExitCode.DEPLOYMENT
    assert "required artifact does not exist" in capsys.readouterr().err


def test_verify_missing_build_uses_verification_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AFTWIN_BUILD_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as raised:
        main(["verify", "--site", "missing", "--output", "json"])

    assert raised.value.code == ExitCode.VERIFICATION
    assert '"code": "runtime_verification_failed"' in capsys.readouterr().err


def test_scenario_invalid_path_uses_verification_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.yaml"

    with pytest.raises(SystemExit) as raised:
        main(["scenario", "run", "--path", str(missing), "--output", "json"])

    assert raised.value.code == ExitCode.VERIFICATION
    assert '"code": "runtime_verification_failed"' in capsys.readouterr().err
