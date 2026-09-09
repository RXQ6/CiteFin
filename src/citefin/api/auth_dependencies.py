"""Authenticated user resolution with an explicit internal compatibility path."""

from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status

from citefin.api.dependencies import DatabaseSession, SettingsDependency
from citefin.services.auth import resolve_session_user

SESSION_COOKIE = "citefin_session"


def resolve_current_user_id(
    session: DatabaseSession,
    settings: SettingsDependency,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    legacy_user_id: Annotated[str | None, Header(alias="X-User-ID", max_length=128)] = None,
) -> str:
    """Prefer a secure session and allow the legacy header outside public production."""

    if session_token:
        user_id = resolve_session_user(session, settings, session_token)
        if user_id:
            return user_id
    if (
        legacy_user_id
        and settings.legacy_user_header_enabled
        and settings.environment != "production"
    ):
        return legacy_user_id
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "authentication_required", "message": "请先登录后继续。"},
    )


CurrentUserId = Annotated[str, Depends(resolve_current_user_id)]
