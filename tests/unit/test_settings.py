from pathlib import Path

import pytest

from aftwin.settings import Settings


def test_settings_have_local_defaults() -> None:
    settings = Settings()

    assert settings.netbox_url == "http://localhost:8000"
    assert settings.netbox_token is None
    assert settings.site == "aif-lab"
    assert settings.build_dir == Path("build")


def test_settings_follow_documented_environment_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NETBOX_URL", "https://netbox.example.test")
    monkeypatch.setenv("NETBOX_TOKEN", "secret-value")
    monkeypatch.setenv("AFTWIN_SITE", "test-lab")

    settings = Settings()

    assert settings.netbox_url == "https://netbox.example.test"
    assert settings.netbox_token is not None
    assert settings.netbox_token.get_secret_value() == "secret-value"
    assert settings.site == "test-lab"
