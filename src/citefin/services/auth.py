"""Privacy-minimized email challenge and browser session services."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib import request as urlrequest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citefin.config import Settings
from citefin.db.models import AuthLoginCode, AuthSession
from citefin.ids import new_prefixed_id

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthError(Exception):
    """Stable authentication failure safe for API clients."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class LoginChallenge:
    code_id: str
    code: str
    expires_at: datetime


@dataclass(frozen=True)
class SessionGrant:
    user_id: str
    token: str
    expires_at: datetime


def _digest(settings: Settings, purpose: str, value: str) -> str:
    payload = f"{purpose}:{value}".encode()
    return hmac.new(settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def normalize_email(email: str) -> str:
    """Normalize a transient address without persisting or logging it."""

    normalized = email.strip().casefold()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise AuthError("invalid_email", "请输入有效的邮箱地址。", 422)
    return normalized


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def create_login_challenge(
    session: Session,
    settings: Settings,
    email: str,
    client_ip: str,
    *,
    now: datetime | None = None,
) -> LoginChallenge:
    """Create one rate-limited hashed challenge; raw email and code stay transient."""

    current = now or datetime.now(UTC)
    normalized = normalize_email(email)
    email_hash = _digest(settings, "email", normalized)
    ip_hash = _digest(settings, "ip", client_ip or "unknown")
    cutoff = current - timedelta(minutes=15)
    email_count = session.scalar(
        select(func.count())
        .select_from(AuthLoginCode)
        .where(AuthLoginCode.email_hash == email_hash, AuthLoginCode.created_at >= cutoff)
    )
    ip_count = session.scalar(
        select(func.count())
        .select_from(AuthLoginCode)
        .where(AuthLoginCode.request_ip_hash == ip_hash, AuthLoginCode.created_at >= cutoff)
    )
    if (email_count or 0) >= 5 or (ip_count or 0) >= 20:
        raise AuthError("auth_rate_limited", "请求过于频繁，请稍后再试。", 429)
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = AuthLoginCode(
        code_id=new_prefixed_id("authcode"),
        email_hash=email_hash,
        code_hash=_digest(settings, "code", f"{email_hash}:{code}"),
        request_ip_hash=ip_hash,
        attempts=0,
        expires_at=current + timedelta(seconds=settings.auth_code_ttl_seconds),
        consumed_at=None,
        created_at=current,
    )
    session.add(challenge)
    session.commit()
    return LoginChallenge(challenge.code_id, code, challenge.expires_at)


def deliver_login_code(settings: Settings, email: str, code: str) -> None:
    """Deliver via a configured webhook without logging credentials or payloads."""

    if settings.auth_email_mode == "development":
        return
    if not settings.auth_email_webhook_url or not settings.auth_email_webhook_token:
        raise AuthError("email_delivery_not_configured", "邮件服务尚未配置。", 503)
    payload = json.dumps(
        {
            "to": normalize_email(email),
            "template": "citefin-login-code",
            "variables": {"code": code},
        }
    ).encode()
    outbound = urlrequest.Request(
        settings.auth_email_webhook_url,
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.auth_email_webhook_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(outbound, timeout=8) as response:
            if response.status >= 300:
                raise AuthError("email_delivery_failed", "验证码发送失败，请稍后重试。", 502)
    except AuthError:
        raise
    except OSError as error:
        raise AuthError("email_delivery_failed", "验证码发送失败，请稍后重试。", 502) from error


def verify_login_challenge(
    session: Session,
    settings: Settings,
    email: str,
    code: str,
    *,
    now: datetime | None = None,
) -> SessionGrant:
    """Consume the latest valid challenge and issue a hashed revocable session."""

    current = now or datetime.now(UTC)
    normalized = normalize_email(email)
    email_hash = _digest(settings, "email", normalized)
    challenge = session.scalar(
        select(AuthLoginCode)
        .where(AuthLoginCode.email_hash == email_hash, AuthLoginCode.consumed_at.is_(None))
        .order_by(AuthLoginCode.created_at.desc())
    )
    if challenge is None or _as_utc(challenge.expires_at) <= current:
        raise AuthError("auth_code_expired", "验证码无效或已过期。", 401)
    if challenge.attempts >= 5:
        raise AuthError("auth_code_locked", "验证码尝试次数已用完，请重新获取。", 429)
    expected = _digest(settings, "code", f"{email_hash}:{code.strip()}")
    if not hmac.compare_digest(challenge.code_hash, expected):
        challenge.attempts += 1
        session.commit()
        raise AuthError("auth_code_invalid", "验证码不正确。", 401)
    challenge.consumed_at = current
    token = secrets.token_urlsafe(32)
    user_id = f"user_{email_hash[:24]}"
    expires_at = current + timedelta(hours=settings.auth_session_ttl_hours)
    session.add(
        AuthSession(
            session_id=new_prefixed_id("session"),
            user_id=user_id,
            email_hash=email_hash,
            token_hash=_digest(settings, "session", token),
            expires_at=expires_at,
            revoked_at=None,
            created_at=current,
        )
    )
    session.commit()
    return SessionGrant(user_id, token, expires_at)


def resolve_session_user(
    session: Session, settings: Settings, token: str, *, now: datetime | None = None
) -> str | None:
    """Resolve an unexpired session token without exposing stored hashes."""

    current = now or datetime.now(UTC)
    auth_session = session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == _digest(settings, "session", token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if auth_session is None or _as_utc(auth_session.expires_at) <= current:
        return None
    return auth_session.user_id


def revoke_session(session: Session, settings: Settings, token: str) -> None:
    """Idempotently revoke one browser session."""

    auth_session = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == _digest(settings, "session", token))
    )
    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(UTC)
        session.commit()
