"""F012 API and persistence tests."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AuditEvent, Claim, Evaluation, Report
from citefin.db.session import build_engine
from citefin.main import create_app


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'evaluations.db').as_posix()}")
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
            "company_name": "评测示例股份有限公司",
            "security_code": "600006",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def _insert_candidate(sessions: sessionmaker[Session], run_id: str, *, invalid: bool) -> str:
    now = datetime.now(UTC)
    report_id = "report_eval_invalid" if invalid else "report_eval_valid"
    claim_id = "claim_eval_major" if invalid else None
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
    claim_ids: list[str] = []
    with sessions() as session:
        if claim_id is not None:
            session.add(
                Claim(
                    claim_id=claim_id,
                    run_id=run_id,
                    claim_type="inference",
                    text="未提供证据的重大结论。",
                    materiality="major",
                    status="supported",
                    evidence_ids=[],
                    created_by="test",
                    created_at=now,
                )
            )
            claim_ids.append(claim_id)
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


def test_evaluation_persists_result_and_replays_without_verifying_run(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "evaluation_user", "evaluation-key-1234")
    report_id = _insert_candidate(sessions, run_id, invalid=False)
    endpoint = f"/api/v1/analysis-runs/{run_id}/evaluations"

    first = client.post(
        endpoint,
        headers={"X-User-ID": "evaluation_user"},
        json={"report_id": report_id},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "passed"
    assert body["evaluator_version"] == "deterministic-evaluator-v1"
    assert body["idempotent_replay"] is False
    assert body["input_snapshot"]["report_id"] == report_id
    assert all(check["result"] == "passed" for check in body["checks"])

    replay = client.post(
        endpoint,
        headers={"X-User-ID": "evaluation_user"},
        json={"report_id": report_id},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["evaluation_id"] == body["evaluation_id"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Evaluation)) == 1
        report = session.get(Report, report_id)
        assert report is not None and report.status == "candidate"


def test_failed_evaluation_returns_repair_instruction_and_respects_user_scope(
    tmp_path: Path,
) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "evaluation_user", "evaluation-key-5678")
    report_id = _insert_candidate(sessions, run_id, invalid=True)
    endpoint = f"/api/v1/analysis-runs/{run_id}/evaluations"

    failed = client.post(
        endpoint,
        headers={"X-User-ID": "evaluation_user"},
        json={"report_id": report_id},
    )
    assert failed.status_code == 201
    body = failed.json()
    assert body["status"] == "failed"
    assert body["node_hint"] == "build_evidence_map"
    assert body["repair_instruction"]
    assert any(reason["code"] == "claim_evidence_coverage" for reason in body["blocking_reasons"])

    foreign = client.post(
        endpoint,
        headers={"X-User-ID": "other_user"},
        json={"report_id": report_id},
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"]["code"] == "run_not_found"
