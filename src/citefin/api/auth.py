"""Email challenge and secure browser session API."""

from datetime import datetime
from typing import NoReturn

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from citefin.api.auth_dependencies import SESSION_COOKIE
from citefin.api.dependencies import DatabaseSession, SettingsDependency
from citefin.services.auth import (
    AuthError,
    create_login_challenge,
    deliver_login_code,
    resolve_session_user,
    revoke_session,
    verify_login_challenge,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


class EmailRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class EmailVerifyRequest(EmailRequest):
    code: str = Field(pattern=r"^\d{6}$")


class ChallengeResponse(BaseModel):
    status: str
    expires_at: datetime
    development_code: str | None = None


class SessionResponse(BaseModel):
    authenticated: bool
    user_id: str | None
    expires_at: datetime | None = None


def _raise_auth(error: AuthError) -> NoReturn:
    raise HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    ) from error


@router.post("/email/request", response_model=ChallengeResponse)
def request_email_code(
    payload: EmailRequest,
    request: Request,
    session: DatabaseSession,
    settings: SettingsDependency,
) -> ChallengeResponse:
    try:
        challenge = create_login_challenge(
            session,
            settings,
            payload.email,
            request.client.host if request.client else "unknown",
        )
        deliver_login_code(settings, payload.email, challenge.code)
    except AuthError as error:
        _raise_auth(error)
    return ChallengeResponse(
        status="code_sent",
        expires_at=challenge.expires_at,
        development_code=challenge.code if settings.environment != "production" else None,
    )


@router.post("/email/verify", response_model=SessionResponse)
def verify_email_code(
    payload: EmailVerifyRequest,
    response: Response,
    session: DatabaseSession,
    settings: SettingsDependency,
) -> SessionResponse:
    try:
        grant = verify_login_challenge(session, settings, payload.email, payload.code)
    except AuthError as error:
        _raise_auth(error)
    response.set_cookie(
        SESSION_COOKIE,
        grant.token,
        max_age=settings.auth_session_ttl_hours * 3600,
        expires=grant.expires_at,
        secure=settings.environment == "production",
        httponly=True,
        samesite="lax",
        path="/",
    )
    return SessionResponse(authenticated=True, user_id=grant.user_id, expires_at=grant.expires_at)


@router.get("/session", response_model=SessionResponse)
def get_auth_session(
    request: Request, session: DatabaseSession, settings: SettingsDependency
) -> SessionResponse:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = resolve_session_user(session, settings, token) if token else None
    return SessionResponse(authenticated=user_id is not None, user_id=user_id)


@router.post("/logout", response_model=SessionResponse)
def logout(
    request: Request,
    response: Response,
    session: DatabaseSession,
    settings: SettingsDependency,
) -> SessionResponse:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(session, settings, token)
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax")
    return SessionResponse(authenticated=False, user_id=None)
