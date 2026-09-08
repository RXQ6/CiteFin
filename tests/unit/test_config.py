from pathlib import Path

from pytest import MonkeyPatch

from citefin.config import Settings, get_settings


def test_settings_use_safe_defaults(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("CITEFIN_ENVIRONMENT", raising=False)
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.database_url is None
    assert settings.redis_url is None
    assert settings.object_storage_root == Path("data/objects")
    assert settings.max_upload_bytes == 50 * 1024 * 1024


def test_cached_settings_ignore_dotenv_in_test_environment(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "CITEFIN_DATABASE_URL=postgresql://must-not-be-read\n"
        "CITEFIN_REDIS_URL=redis://must-not-be-read\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CITEFIN_ENVIRONMENT", "test")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.environment == "test"
    assert settings.database_url is None
    assert settings.redis_url is None
