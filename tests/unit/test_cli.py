import pytest

from aftwin.cli import main
from aftwin.errors import ExitCode


def test_pending_command_uses_stable_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(["compile"])

    assert raised.value.code == ExitCode.CONFIGURATION
    assert "planned for M3" in capsys.readouterr().err


def test_pending_command_can_render_json(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["compile", "--output", "json"])

    assert '"code": "command_not_implemented"' in capsys.readouterr().err


def test_validate_requires_netbox_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NETBOX_TOKEN", raising=False)
    monkeypatch.delenv("AFTWIN_NETBOX_TOKEN", raising=False)

    with pytest.raises(SystemExit) as raised:
        main(["validate"])

    assert raised.value.code == ExitCode.CONFIGURATION
    assert "NETBOX_TOKEN is not configured" in capsys.readouterr().err
