"""F008 audit-boundary tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AnalysisRun, AuditEvent
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.workflow import FinanceAgentState, WorkflowError, WorkflowNode, advance_state


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'workflow.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        object_storage_root=tmp_path / "objects",
        max_upload_bytes=1024 * 1024,
        min_pdf_text_characters=20,
    )

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application), sessions


def _run(client: TestClient) -> str:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": "workflow_user", "Idempotency-Key": "workflow-key-1234"},
        json={
            "company_name": "工作流示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def test_owned_transition_updates_run_and_audit_event(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _run(client)
    state = FinanceAgentState(
        run_id=run_id,
        current_node=WorkflowNode.CREATE_RUN,
        status="created",
        as_of=datetime(2026, 4, 11, tzinfo=UTC),
    )
    with sessions() as session:
        next_state = advance_state(
            session,
            state,
            "workflow_user",
            WorkflowNode.REQUEST_GUARD,
            status="validating",
        )
    assert next_state.current_node == WorkflowNode.REQUEST_GUARD
    with sessions() as session:
        run = session.get(AnalysisRun, run_id)
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == run_id, AuditEvent.event_type == "node_transition"
            )
        )
        assert run is not None and run.current_node == "request_guard"
        assert event is not None


def test_invalid_or_foreign_transition_is_rejected(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _run(client)
    state = FinanceAgentState(
        run_id=run_id,
        current_node=WorkflowNode.CREATE_RUN,
        status="created",
        as_of=datetime(2026, 4, 11, tzinfo=UTC),
    )
    with sessions() as session, pytest.raises(WorkflowError, match="Cannot transition"):
        advance_state(session, state, "workflow_user", WorkflowNode.FINALIZE)
    with sessions() as session, pytest.raises(WorkflowError, match="not found"):
        advance_state(session, state, "other_user", WorkflowNode.REQUEST_GUARD)


def test_verified_transition_requires_goal_gate_event(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _run(client)
    state = FinanceAgentState(
        run_id=run_id,
        current_node=WorkflowNode.GOAL_EVALUATOR,
        status="evaluating",
        as_of=datetime(2026, 4, 11, tzinfo=UTC),
    )
    with sessions() as session, pytest.raises(WorkflowError, match="Only Goal Gate"):
        advance_state(
            session,
            state,
            "workflow_user",
            WorkflowNode.FINALIZE,
            status="verified",
        )
