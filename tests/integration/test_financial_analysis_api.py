"""F009 API and persistence tests for deterministic financial analysis claims."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AuditEvent, CalculatedMetric, Claim, Evidence
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.services.metrics import METRIC_DEFINITION_VERSION, METRIC_DEFINITIONS


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'analysis.db').as_posix()}")
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
            "company_name": "分析示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def _insert_metrics(sessions: sessionmaker[Session], run_id: str) -> None:
    now = datetime.now(UTC)
    values = {definition.code: Decimal("1") for definition in METRIC_DEFINITIONS}
    values["accounts_receivable_growth"] = Decimal("0.2")
    values["revenue_growth"] = Decimal("0.1")
    with sessions() as session:
        for definition in METRIC_DEFINITIONS:
            session.add(
                CalculatedMetric(
                    metric_id=f"metric_{definition.code}",
                    run_id=run_id,
                    metric_code=definition.code,
                    definition_version=METRIC_DEFINITION_VERSION,
                    period_end=date(2025, 12, 31),
                    input_fact_ids=[f"fact_{definition.code}"],
                    input_snapshot={},
                    value=values[definition.code],
                    unit=definition.unit,
                    status="calculated",
                    calculator_version="test-calculator",
                    calculated_at=now,
                )
            )
        session.commit()


def test_financial_analysis_persists_supported_claims_and_replays(
    tmp_path: Path,
) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "analysis_user", "analysis-key-1234")
    _insert_metrics(sessions, run_id)
    endpoint = f"/api/v1/analysis-runs/{run_id}/financial-analysis"

    first = client.post(
        endpoint,
        headers={"X-User-ID": "analysis_user"},
        json={"period_end": "2025-12-31"},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["idempotent_replay"] is False
    assert len(body["claims"]) == 19
    assert {claim["claim_type"] for claim in body["claims"]} == {"calculation", "inference"}
    assert all(claim["status"] == "supported" for claim in body["claims"])

    replay = client.post(
        endpoint,
        headers={"X-User-ID": "analysis_user"},
        json={"period_end": "2025-12-31"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["claims"] == body["claims"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Claim)) == 19
        assert session.scalar(select(func.count()).select_from(Evidence)) == 25
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "financial_analysis_completed")
        )
        assert event is not None


def test_financial_analysis_requires_owned_run_and_complete_metrics(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "analysis_user", "analysis-key-5678")
    endpoint = f"/api/v1/analysis-runs/{run_id}/financial-analysis"
    missing_metrics = client.post(
        endpoint,
        headers={"X-User-ID": "analysis_user"},
        json={"period_end": "2025-12-31"},
    )
    assert missing_metrics.status_code == 422
    assert missing_metrics.json()["detail"]["code"] == "incomplete_metric_set"
    assert sessions is not None

    wrong_user = client.post(
        "/api/v1/analysis-runs/run_missing/financial-analysis",
        headers={"X-User-ID": "other_user"},
        json={"period_end": "2025-12-31"},
    )
    assert wrong_user.status_code == 404
    assert wrong_user.json()["detail"]["code"] == "run_not_found"


def test_financial_analysis_rejects_metric_period_mismatch(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "analysis_user", "analysis-key-9012")
    _insert_metrics(sessions, run_id)
    response = client.post(
        f"/api/v1/analysis-runs/{run_id}/financial-analysis",
        headers={"X-User-ID": "analysis_user"},
        json={"period_end": "2024-12-31"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "incomplete_metric_set"
