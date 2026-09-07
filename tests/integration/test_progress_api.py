"""F015 owned progress and replayable lifecycle-event tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.db.base import Base
from citefin.db.models import AuditEvent, Task
from citefin.db.session import build_engine
from citefin.ids import new_prefixed_id
from citefin.main import create_app


@pytest.fixture
def progress_harness(tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'progress.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    with TestClient(application) as client:
        yield client, sessions
    engine.dispose()


def _create_run(client: TestClient, user_id: str = "progress_user") -> dict[str, str]:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": user_id, "Idempotency-Key": f"progress-key-{user_id}"},
        json={
            "company_name": "Progress 示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()


def _append_failed_event(sessions: sessionmaker[Session], run_id: str) -> str:
    event_id = new_prefixed_id("event")
    with sessions() as session:
        task = session.scalar(select(Task).where(Task.run_id == run_id))
        assert task is not None
        task.status = "failed"
        task.error = {"code": "parse_failed", "message": "internal detail"}
        session.add(
            AuditEvent(
                event_id=event_id,
                run_id=run_id,
                trace_id=new_prefixed_id("trace"),
                node="document_parse",
                event_type="node_failed",
                status="failed",
                payload={
                    "error_code": "parse_failed",
                    "prompt": "must not leave this boundary",
                    "secret": "must not leave this boundary",
                },
                created_at=datetime.now(UTC),
            )
        )
        session.commit()
    return event_id


def test_progress_returns_owned_status_tasks_and_redacted_errors(
    progress_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = progress_harness
    run = _create_run(client)
    initial = client.get(
        f"/api/v1/analysis-runs/{run['run_id']}/progress",
        headers={"X-User-ID": "progress_user"},
    )
    assert initial.status_code == 200
    assert initial.json()["status"] == "created"
    assert initial.json()["current_node"] == "create_run"
    assert initial.json()["tasks"][0]["task_id"] == run["task_id"]
    assert initial.json()["recent_errors"] == []

    _append_failed_event(sessions, run["run_id"])
    response = client.get(
        f"/api/v1/analysis-runs/{run['run_id']}/progress?error_limit=1",
        headers={"X-User-ID": "progress_user"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tasks"][0]["error_code"] == "parse_failed"
    assert body["recent_errors"][0]["code"] == "parse_failed"
    assert "must not leave this boundary" not in response.text
    assert "secret" not in response.text


def test_progress_and_events_are_user_scoped(
    progress_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = progress_harness
    run = _create_run(client)
    progress = client.get(
        f"/api/v1/analysis-runs/{run['run_id']}/progress",
        headers={"X-User-ID": "other_user"},
    )
    events = client.get(
        f"/api/v1/analysis-runs/{run['run_id']}/events",
        headers={"X-User-ID": "other_user"},
    )
    assert progress.status_code == 404
    assert progress.json()["detail"]["code"] == "analysis_run_not_found"
    assert events.status_code == 404
    assert events.json()["detail"]["code"] == "analysis_run_not_found"


def test_sse_events_are_ordered_and_reconnect_after_last_event_id(
    progress_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = progress_harness
    run = _create_run(client)
    events_url = f"/api/v1/analysis-runs/{run['run_id']}/events?limit=1"
    with client.stream("GET", events_url, headers={"X-User-ID": "progress_user"}) as first:
        assert first.status_code == 200
        assert first.headers["content-type"].startswith("text/event-stream")
        first.read()
        first_body = first.text
    first_event_id = next(line[4:] for line in first_body.splitlines() if line.startswith("id: "))
    assert "event: lifecycle" in first_body
    assert first.headers["X-Events-More"] == "false"

    second_event_id = _append_failed_event(sessions, run["run_id"])
    with client.stream(
        "GET",
        events_url,
        headers={"X-User-ID": "progress_user", "Last-Event-ID": first_event_id},
    ) as replay:
        assert replay.status_code == 200
        replay.read()
        replay_body = replay.text
    assert second_event_id in replay_body
    assert first_event_id not in replay_body
    assert "prompt" not in replay_body
    assert "secret" not in replay_body


def test_sse_rejects_unknown_cursor_and_invalid_limit(
    progress_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = progress_harness
    run = _create_run(client)
    unknown = client.get(
        f"/api/v1/analysis-runs/{run['run_id']}/events?after=event_unknown",
        headers={"X-User-ID": "progress_user"},
    )
    invalid_limit = client.get(
        f"/api/v1/analysis-runs/{run['run_id']}/progress?error_limit=0",
        headers={"X-User-ID": "progress_user"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "invalid_event_cursor"
    assert invalid_limit.status_code == 422
