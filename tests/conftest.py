"""Cross-suite fixtures that keep tests isolated from developer configuration."""

from collections.abc import Iterator

import pytest
from pytest import MonkeyPatch

from citefin.config import get_settings
from citefin.db.session import get_session_factory


@pytest.fixture(autouse=True)
def isolate_runtime_configuration(monkeypatch: MonkeyPatch) -> Iterator[None]:
    """Disable repository .env loading and clear process-level factories per test."""

    monkeypatch.setenv("CITEFIN_ENVIRONMENT", "test")
    monkeypatch.delenv("CITEFIN_DATABASE_URL", raising=False)
    monkeypatch.delenv("CITEFIN_REDIS_URL", raising=False)
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_settings.cache_clear()
    get_session_factory.cache_clear()
