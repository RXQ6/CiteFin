"""Authentication isolation, privacy, rate-limit, and cookie API tests."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AnalysisRun, AuthLoginCode, AuthSession
from citefin.db.session import build_engine
from citefin.main import create_app


@dataclass(frozen=True)
class AuthHarness:
    client: TestClient
    sessions: sessionmaker[Session]


@pytest.fixture
def auth_harness(tmp_path: Path) -> Iterator[AuthHarness]:
    database_path = tmp_path / "auth.db"
    engine = build_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite+pysqlite:///{database_path.as_posix()}",
        session_secret="test-session-secret-with-enough-entropy",
    )

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        yield AuthHarness(client=client, sessions=sessions)
    engine.dispose()


def _request_code(harness: AuthHarness, email: str = "Researcher@Example.com") -> str:
    response = harness.client.post("/api/v1/auth/email/request", json={"email": email})
    assert response.status_code == 200
    code = response.json()["development_code"]
    assert isinstance(code, str) and len(code) == 6 and code.isdigit()
    return code


def test_email_login_uses_hashed_storage_and_authorizes_run(auth_harness: AuthHarness) -> None:
    code = _request_code(auth_harness)

    with auth_harness.sessions() as session:
        challenge = session.scalar(select(AuthLoginCode))
        assert challenge is not None
        assert "researcher" not in challenge.email_hash
        assert code not in challenge.code_hash
        assert len(challenge.email_hash) == len(challenge.code_hash) == 64

    wrong = auth_harness.client.post(
        "/api/v1/auth/email/verify",
        json={
            "email": "researcher@example.com",
            "code": "000000" if code != "000000" else "999999",
        },
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "auth_code_invalid"

    verified = auth_harness.client.post(
        "/api/v1/auth/email/verify",
        json={"email": "researcher@example.com", "code": code},
    )
    assert verified.status_code == 200
    assert verified.json()["authenticated"] is True
    assert "HttpOnly" in verified.headers["set-cookie"]
    assert "SameSite=lax" in verified.headers["set-cookie"]

    current = auth_harness.client.get("/api/v1/auth/session")
    assert current.status_code == 200
    assert current.json()["authenticated"] is True

    created = auth_harness.client.post(
        "/api/v1/analysis-runs",
        headers={"Idempotency-Key": "authenticated-create"},
        json={
            "company_name": "合成研究样例公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-01T00:00:00Z",
            "analysis_focus": ["comprehensive"],
        },
    )
    assert created.status_code == 201
    with auth_harness.sessions() as session:
        run = session.scalar(select(AnalysisRun))
        stored_session = session.scalar(select(AuthSession))
        assert run is not None and run.user_id.startswith("user_")
        assert stored_session is not None and len(stored_session.token_hash) == 64
        assert stored_session.token_hash not in verified.headers["set-cookie"]

    logged_out = auth_harness.client.post("/api/v1/auth/logout")
    assert logged_out.status_code == 200
    assert logged_out.json()["authenticated"] is False
    assert auth_harness.client.get("/api/v1/auth/session").json()["authenticated"] is False


def test_request_validation_expiry_and_dual_rate_limit(auth_harness: AuthHarness) -> None:
    invalid = auth_harness.client.post("/api/v1/auth/email/request", json={"email": "not-an-email"})
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_email"

    for _ in range(5):
        assert (
            auth_harness.client.post(
                "/api/v1/auth/email/request", json={"email": "limited@example.com"}
            ).status_code
            == 200
        )
    limited = auth_harness.client.post(
        "/api/v1/auth/email/request", json={"email": "limited@example.com"}
    )
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "auth_rate_limited"

    no_challenge = auth_harness.client.post(
        "/api/v1/auth/email/verify",
        json={"email": "missing@example.com", "code": "123456"},
    )
    assert no_challenge.status_code == 401
    assert no_challenge.json()["detail"]["code"] == "auth_code_expired"


def test_production_rejects_legacy_user_header(tmp_path: Path) -> None:
    database_path = tmp_path / "production-auth.db"
    engine = build_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        environment="production",
        database_url=f"sqlite+pysqlite:///{database_path.as_posix()}",
        session_secret="production-test-secret",
        legacy_user_header_enabled=True,
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/analysis-runs",
            headers={"X-User-ID": "spoofed", "Idempotency-Key": "blocked"},
            json={
                "company_name": "合成研究样例公司",
                "security_code": "600001",
                "report_period_end": "2025-12-31",
                "as_of": "2026-04-01T00:00:00Z",
                "analysis_focus": ["comprehensive"],
            },
        )
    engine.dispose()

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
