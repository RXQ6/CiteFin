"""End-to-end API and persistence tests for F002."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AnalysisRun, AuditEvent, Task, WorkflowCheckpoint
from citefin.db.session import build_engine
from citefin.main import create_app


@dataclass(frozen=True)
class ApiHarness:
    """A client and session factory sharing one isolated database."""

    client: TestClient
    sessions: sessionmaker[Session]


@pytest.fixture
def api_harness(tmp_path: Path) -> Iterator[ApiHarness]:
    database_path = tmp_path / "f002.db"
    engine = build_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    with TestClient(application) as client:
        yield ApiHarness(client=client, sessions=sessions)
    engine.dispose()


def valid_payload() -> dict[str, object]:
    return {
        "company_name": "贵州茅台酒股份有限公司",
        "security_code": "600519",
        "report_period_end": "2025-12-31",
        "as_of": "2026-04-01T08:00:00+08:00",
        "analysis_focus": ["profitability", "cashflow"],
    }


def request_headers(user_id: str = "user_demo") -> dict[str, str]:
    return {"X-User-ID": user_id, "Idempotency-Key": "annual-2025-600519"}


def test_create_run_persists_complete_initial_bundle(api_harness: ApiHarness) -> None:
    response = api_harness.client.post(
        "/api/v1/analysis-runs", json=valid_payload(), headers=request_headers()
    )

    assert response.status_code == 201
    body = response.json()
    assert body["run_id"].startswith("run_")
    assert body["task_id"].startswith("task_")
    assert body["event_id"].startswith("event_")
    assert body["checkpoint_id"].startswith("checkpoint_")
    assert body["thread_id"].startswith("thread_")
    assert body["status"] == "created"
    assert body["current_node"] == "create_run"
    assert body["idempotent_replay"] is False
    assert body["as_of"] == "2026-04-01T00:00:00Z"

    with api_harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        task = session.scalar(select(Task))
        event = session.scalar(select(AuditEvent))
        checkpoint = session.scalar(select(WorkflowCheckpoint))
        assert task is not None and task.status == "ready"
        assert event is not None and event.event_type == "run_created"
        assert checkpoint is not None and checkpoint.state_version == 1
        assert checkpoint.state_data["run_id"] == body["run_id"]
        assert checkpoint.state_data["tasks"] == [body["task_id"]]


def test_same_user_and_idempotency_key_replays_original_bundle(
    api_harness: ApiHarness,
) -> None:
    first = api_harness.client.post(
        "/api/v1/analysis-runs", json=valid_payload(), headers=request_headers()
    )
    replay_payload = valid_payload() | {"company_name": "不会覆盖原始运行"}
    second = api_harness.client.post(
        "/api/v1/analysis-runs", json=replay_payload, headers=request_headers()
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["checkpoint_id"] == first.json()["checkpoint_id"]
    assert second.json()["company_name"] == "贵州茅台酒股份有限公司"
    assert second.json()["idempotent_replay"] is True

    with api_harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert session.scalar(select(func.count()).select_from(Task)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert session.scalar(select(func.count()).select_from(WorkflowCheckpoint)) == 1


def test_idempotency_key_is_scoped_to_user(api_harness: ApiHarness) -> None:
    first = api_harness.client.post(
        "/api/v1/analysis-runs", json=valid_payload(), headers=request_headers("user_a")
    )
    second = api_harness.client.post(
        "/api/v1/analysis-runs", json=valid_payload(), headers=request_headers("user_b")
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["run_id"] != second.json()["run_id"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("security_code", "AAPL"),
        ("security_code", "999999"),
        ("analysis_focus", ["comprehensive", "cashflow"]),
        ("analysis_focus", ["cashflow", "cashflow"]),
    ],
)
def test_invalid_run_request_is_rejected(
    api_harness: ApiHarness, field: str, value: object
) -> None:
    payload = valid_payload() | {field: value}

    response = api_harness.client.post(
        "/api/v1/analysis-runs", json=payload, headers=request_headers()
    )

    assert response.status_code == 422
    with api_harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 0


def test_future_report_period_is_rejected(api_harness: ApiHarness) -> None:
    future_period = date.today() + timedelta(days=1)
    payload = valid_payload() | {
        "report_period_end": future_period.isoformat(),
        "as_of": f"{date.today().isoformat()}T00:00:00Z",
    }

    response = api_harness.client.post(
        "/api/v1/analysis-runs", json=payload, headers=request_headers()
    )

    assert response.status_code == 422


def test_missing_database_configuration_is_actionable() -> None:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, database_url=None
    )
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/analysis-runs", json=valid_payload(), headers=request_headers()
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "database_not_configured"
