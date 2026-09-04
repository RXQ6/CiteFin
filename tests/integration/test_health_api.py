from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from citefin.config import get_settings
from citefin.main import app


def test_liveness_exposes_version_and_dependency_state() -> None:
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "live",
        "service": "citefin-api",
        "version": "0.1.0",
        "environment": "development",
        "dependencies": {
            "postgres": "not_configured",
            "redis": "not_configured",
        },
    }


def test_readiness_reports_configured_dependencies(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CITEFIN_ENVIRONMENT", "test")
    monkeypatch.setenv("CITEFIN_DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("CITEFIN_REDIS_URL", "redis://example")
    get_settings.cache_clear()

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["dependencies"] == {
        "postgres": "configured",
        "redis": "configured",
    }
    get_settings.cache_clear()
