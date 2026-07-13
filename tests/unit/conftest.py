"""Unit-test isolation from developer-local configuration."""

import pytest

from aftwin.settings import Settings


@pytest.fixture(autouse=True)
def ignore_developer_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests deterministic when the documented local .env exists."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in (
        "NETBOX_URL",
        "NETBOX_TOKEN",
        "AFTWIN_NETBOX_URL",
        "AFTWIN_NETBOX_TOKEN",
        "AFTWIN_SITE",
        "AFTWIN_BUILD_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
