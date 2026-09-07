"""F013 Goal Gate API and terminal-state tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AnalysisRun, AuditEvent, Claim, Evaluation, GoalGateDecision, Report
from citefin.db.session import build_engine
from citefin.main import create_app


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'goal-gate.db').as_posix()}")
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


def _create_run(client: TestClient, user_id: str, key: str) -> str:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": user_id, "Idempotency-Key": key},
        json={
            "company_name": "Goal Gate 示例股份有限公司",
            "security_code": "600007",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def _insert_report(sessions: sessionmaker[Session], run_id: str, *, invalid: bool = False) -> str:
    now = datetime.now(UTC)
    report_id = "report_gate_invalid" if invalid else "report_gate_valid"
    claim_id = "claim_gate_major" if invalid else None
    claim_ids = [claim_id] if claim_id is not None else []
    content: dict[str, object] = {
        "schema_version": "financial-report-v1",
        "run": {"run_id": run_id},
        "facts": [],
        "calculations": {"metrics": [], "claims": []},
        "inferences": [],
        "risks": [],
        "limitations": {"claims": [], "risk_limitations": []},
        "evidence": {},
    }
    with sessions() as session:
        if claim_id is not None:
            session.add(
                Claim(
                    claim_id=claim_id,
                    run_id=run_id,
                    claim_type="inference",
                    text="缺少证据的重大结论。",
                    materiality="major",
                    status="supported",
                    evidence_ids=[],
                    created_by="test",
                    created_at=now,
                )
            )
        session.add(
            Report(
                report_id=report_id,
                run_id=run_id,
                version=1,
                status="candidate",
                schema_version="financial-report-v1",
                content=content,
                claim_ids=claim_ids,
                generated_by="test-report",
                created_at=now,
            )
        )
        session.add(
            AuditEvent(
                event_id=f"event_{report_id}",
                run_id=run_id,
                trace_id=f"trace_{report_id}",
                node="write_report",
                event_type="report_candidate_generated",
                status="success",
                payload={"report_id": report_id},
                created_at=now,
            )
        )
        session.commit()
    return report_id


def _evaluate(client: TestClient, run_id: str, report_id: str) -> dict[str, object]:
    response = client.post(
        f"/api/v1/analysis-runs/{run_id}/evaluations",
        headers={"X-User-ID": "gate_user"},
        json={"report_id": report_id},
    )
    assert response.status_code == 201
    return response.json()


def test_goal_gate_verifies_only_after_passing_evaluation_and_replays(
    tmp_path: Path,
) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "gate_user", "gate-key-1234")
    report_id = _insert_report(sessions, run_id)
    evaluation = _evaluate(client, run_id, report_id)
    assert evaluation["status"] == "passed"

    endpoint = f"/api/v1/analysis-runs/{run_id}/goal-gate"
    first = client.post(
        endpoint,
        headers={"X-User-ID": "gate_user"},
        json={"report_id": report_id},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["decision"] == "verified"
    assert body["evaluation_id"] == evaluation["evaluation_id"]
    assert body["idempotent_replay"] is False

    replay = client.post(
        endpoint,
        headers={"X-User-ID": "gate_user"},
        json={"report_id": report_id},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["gate_id"] == body["gate_id"]
    with sessions() as session:
        run = session.get(AnalysisRun, run_id)
        report = session.get(Report, report_id)
        assert run is not None and run.status == "verified"
        assert report is not None and report.status == "verified"
        assert session.scalar(select(func.count()).select_from(GoalGateDecision)) == 1
        assert session.scalar(select(func.count()).select_from(Evaluation)) == 1


def test_failed_evaluation_routes_revision_without_verifying_report(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "gate_user", "gate-key-5678")
    report_id = _insert_report(sessions, run_id, invalid=True)
    evaluation = _evaluate(client, run_id, report_id)
    assert evaluation["status"] == "failed"

    response = client.post(
        f"/api/v1/analysis-runs/{run_id}/goal-gate",
        headers={"X-User-ID": "gate_user"},
        json={"report_id": report_id},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "revision_required"
    assert body["node_hint"] == "build_evidence_map"
    assert body["repair_instruction"]
    with sessions() as session:
        report = session.get(Report, report_id)
        assert report is not None and report.status == "candidate"
        event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_type == "goal_gate_decision",
            )
        )
        assert event is not None and event.status == "revision_required"


def test_missing_evaluation_is_blocked_and_user_scope_is_enforced(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "gate_user", "gate-key-9012")
    report_id = _insert_report(sessions, run_id)
    endpoint = f"/api/v1/analysis-runs/{run_id}/goal-gate"

    blocked = client.post(
        endpoint,
        headers={"X-User-ID": "gate_user"},
        json={"report_id": report_id},
    )
    assert blocked.status_code == 201
    assert blocked.json()["decision"] == "blocked"
    assert blocked.json()["node_hint"] == "goal_evaluator"
    foreign = client.post(
        endpoint,
        headers={"X-User-ID": "other_user"},
        json={"report_id": report_id},
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "run_not_found"
