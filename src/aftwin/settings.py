"""Environment-backed application settings."""

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AFTWIN_",
        extra="ignore",
    )

    netbox_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("NETBOX_URL", "AFTWIN_NETBOX_URL"),
    )
    netbox_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("NETBOX_TOKEN", "AFTWIN_NETBOX_TOKEN"),
    )
    site: str = "aif-lab"
    build_dir: Path = Path("build")
