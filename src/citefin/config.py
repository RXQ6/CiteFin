"""Application configuration loaded from environment variables."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with a stable CITEFIN_ environment prefix."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CITEFIN_",
        extra="ignore",
    )

    service_name: str = "citefin-api"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    database_url: str | None = Field(default=None, repr=False)
    redis_url: str | None = Field(default=None, repr=False)
    object_storage_root: Path = Path("data/objects")
    max_upload_bytes: int = 50 * 1024 * 1024
    min_pdf_text_characters: int = 50
    max_pdf_pages: int = 2000
    session_secret: str = Field(default="development-only-change-me", repr=False)
    auth_code_ttl_seconds: int = 600
    auth_session_ttl_hours: int = 168
    auth_email_mode: Literal["development", "webhook"] = "development"
    auth_email_webhook_url: str | None = None
    auth_email_webhook_token: str | None = Field(default=None, repr=False)
    legacy_user_header_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    # Test runs must be hermetic even when a developer has a configured local
    # .env file in the repository root. Explicit process environment values
    # remain available so individual tests can opt into a dependency.
    env_file = None if os.getenv("CITEFIN_ENVIRONMENT") == "test" else ".env"
    return Settings(_env_file=env_file)
