"""Application configuration loaded from environment variables."""

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


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""

    return Settings()
