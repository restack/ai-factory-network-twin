from pathlib import Path
from typing import Any

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


def test_seed_refuses_nonlocal_netbox_without_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NETBOX_URL", "https://netbox.example.test")
    monkeypatch.setenv("NETBOX_TOKEN", "secret-value")

    with pytest.raises(SystemExit) as raised:
        main(["seed"])

    assert raised.value.code == ExitCode.CONFIGURATION
    assert "refusing a non-loopback NetBox target" in capsys.readouterr().err


def test_cli_rejects_path_like_site_before_filesystem_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AFTWIN_BUILD_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as raised:
        main(["deploy", "--site", "../../escaped"])

    assert raised.value.code == ExitCode.CONFIGURATION
    assert "site must start with an alphanumeric" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_validate_uses_configured_site_and_optional_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_fetch(self: object, site_slug: str, *, tag_slug: str | None = None) -> dict[str, Any]:
        del self
        calls.append((site_slug, tag_slug))
        return {
            "site": {"id": 1, "slug": site_slug},
            "devices": [],
            "interfaces": [],
            "cables": [],
            "asns": [],
            "device_roles": [],
            "platforms": [],
            "tags": [],
        }

    monkeypatch.setenv("NETBOX_TOKEN", "secret-value")
    monkeypatch.setenv("AFTWIN_SITE", "configured-site")
    monkeypatch.setenv("AFTWIN_BUILD_DIR", str(tmp_path))
    monkeypatch.setattr("aftwin.cli.NetBoxAdapter.fetch_site", fake_fetch)

    with pytest.raises(SystemExit) as raised:
        main(["validate", "--tag", "ai-fabric"])

    assert raised.value.code == ExitCode.SOURCE_VALIDATION
    assert calls == [("configured-site", "ai-fabric")]


def test_malformed_netbox_values_use_structured_source_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_fetch(self: object, site_slug: str, *, tag_slug: str | None = None) -> dict[str, Any]:
        del self, tag_slug
        return {
            "site": {"id": 1, "slug": site_slug},
            "devices": [
                {
                    "id": 1,
                    "name": "bad-node",
                    "role": {"slug": "invalid-role"},
                    "platform": {"slug": "frr"},
                    "tags": [],
                    "custom_fields": {"fabric_plane": "a"},
                }
            ],
            "interfaces": [],
            "cables": [],
            "asns": [],
            "device_roles": [],
            "platforms": [],
            "tags": [],
        }

    monkeypatch.setenv("NETBOX_TOKEN", "secret-value")
    monkeypatch.setenv("AFTWIN_BUILD_DIR", str(tmp_path))
    monkeypatch.setattr("aftwin.cli.NetBoxAdapter.fetch_site", fake_fetch)

    with pytest.raises(SystemExit) as raised:
        main(["validate", "--output", "json"])

    assert raised.value.code == ExitCode.SOURCE_VALIDATION
    assert '"code": "source_validation_failed"' in capsys.readouterr().err
