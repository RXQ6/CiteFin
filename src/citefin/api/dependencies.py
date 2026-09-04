"""FastAPI dependencies for infrastructure with explicit failure modes."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from citefin.config import Settings, get_settings
from citefin.db.session import get_session_factory

SettingsDependency = Annotated[Settings, Depends(get_settings)]


def get_database_session(settings: SettingsDependency) -> Iterator[Session]:
    """Yield one transaction session or report missing database configuration."""

    if settings.database_url is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "database_not_configured",
                "message": "Set CITEFIN_DATABASE_URL before creating an analysis run.",
            },
        )
    factory = get_session_factory(settings.database_url)
    with factory() as session:
        yield session


DatabaseSession = Annotated[Session, Depends(get_database_session)]
