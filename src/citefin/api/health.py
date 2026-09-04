"""Liveness and readiness endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from citefin import __version__
from citefin.config import Settings, get_settings

router = APIRouter(prefix="/health", tags=["health"])
SettingsDependency = Annotated[Settings, Depends(get_settings)]


class DependencyState(BaseModel):
    """Configuration-level state for a runtime dependency."""

    postgres: Literal["configured", "not_configured"]
    redis: Literal["configured", "not_configured"]


class HealthResponse(BaseModel):
    """Stable health response used by local tooling and orchestration."""

    status: Literal["live", "ready"]
    service: str
    version: str
    environment: str
    dependencies: DependencyState


def _dependency_state(settings: Settings) -> DependencyState:
    return DependencyState(
        postgres="configured" if settings.database_url else "not_configured",
        redis="configured" if settings.redis_url else "not_configured",
    )


@router.get("/live", response_model=HealthResponse)
def live(settings: SettingsDependency) -> HealthResponse:
    """Report process liveness without making network calls."""

    return HealthResponse(
        status="live",
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
        dependencies=_dependency_state(settings),
    )


@router.get("/ready", response_model=HealthResponse)
def ready(settings: SettingsDependency) -> HealthResponse:
    """Report whether required dependency configuration is present."""

    return HealthResponse(
        status="ready",
        service=settings.service_name,
        version=__version__,
        environment=settings.environment,
        dependencies=_dependency_state(settings),
    )
