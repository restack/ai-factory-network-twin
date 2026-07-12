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
