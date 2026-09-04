from pathlib import Path

from citefin.config import Settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.database_url is None
    assert settings.redis_url is None
    assert settings.object_storage_root == Path("data/objects")
    assert settings.max_upload_bytes == 50 * 1024 * 1024
