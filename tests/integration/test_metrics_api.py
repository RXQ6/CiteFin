"""F006 persistence and API tests using a synthetic normalized fact set."""

import json
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
from citefin.db.models import (
    AnalysisRun,
    CalculatedMetric,
    FinancialFact,
    SourceDocument,
    StoredObject,
)
from citefin.db.session import build_engine
from citefin.main import create_app

GOLDEN_ROOT = Path(__file__).parents[1] / "golden"


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'metrics.db').as_posix()}")
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


def _insert_golden_facts(sessions: sessionmaker[Session], run_id: str) -> None:
    expected = json.loads(
        (GOLDEN_ROOT / "cases" / "G003_unit_and_zero_denominator" / "expected.json").read_text(
            encoding="utf-8"
        )
    )
    now = datetime.now(UTC)
    with sessions() as session:
        session.add(
            StoredObject(
                sha256="a" * 64,
                storage_uri="object://" + "a" * 64,
                media_type="application/pdf",
                byte_size=1,
                created_at=now,
            )
        )
        session.add(
            SourceDocument(
                source_id="src_metrics",
                run_id=run_id,
                document_type="annual_report",
                file_name="synthetic.pdf",
                media_type="application/pdf",
                sha256="a" * 64,
                storage_uri="object://" + "a" * 64,
                language="zh-CN",
                page_count=3,
                text_extractable=True,
                parser_version="test",
                ingested_at=now,
            )
        )
        for index, row in enumerate(expected["expected_facts"]):
            session.add(
                FinancialFact(
                    fact_id=f"fact_metrics_{index}",
                    run_id=run_id,
                    source_id="src_metrics",
                    statement_type=row["statement_type"],
                    concept=row["concept"],
                    label_raw=row["row_label"],
                    period_start=(
                        date.fromisoformat(row["period_start"]) if row.get("period_start") else None
                    ),
                    period_end=date.fromisoformat(row["period_end"]),
                    period_type=row["period_type"],
                    scope="consolidated",
                    currency="CNY",
                    display_unit="million_yuan",
                    raw_value=Decimal(row["raw_value"]),
                    normalized_value=Decimal(row["normalized_value"]),
                    sign_convention="signed_v1",
                    page_number=row["page_number"],
                    section=row["statement_type"],
                    row_label=row["row_label"],
                    column_label=row["column_label"],
                    extraction_method="manual",
                    confidence=Decimal("1"),
                    validation_status="extracted",
                    mapping_version="financial-fact-v1",
                    identity_key=f"metrics-{index}",
                    created_at=now,
                )
            )
        session.commit()


def test_calculates_and_replays_persisted_metrics(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": "metric_user", "Idempotency-Key": "metric-key-1234"},
        json={
            "company_name": "云汀软件股份有限公司",
            "security_code": "600003",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["run_id"]
    _insert_golden_facts(sessions, run_id)

    endpoint = f"/api/v1/analysis-runs/{run_id}/metrics/calculate"
    first = client.post(
        endpoint,
        headers={"X-User-ID": "metric_user"},
        json={"period_end": "2025-12-31"},
    )
    assert first.status_code == 201
    assert len(first.json()["metrics"]) == 15
    assert first.json()["idempotent_replay"] is False
    statuses = {row["metric_code"]: row["status"] for row in first.json()["metrics"]}
    assert statuses["net_profit_growth"] == "zero_denominator"
    assert statuses["interest_coverage"] == "zero_denominator"

    replay = client.post(
        endpoint,
        headers={"X-User-ID": "metric_user"},
        json={"period_end": "2025-12-31"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CalculatedMetric)) == 15
        assert session.scalar(select(AnalysisRun).where(AnalysisRun.run_id == run_id)) is not None


def test_metrics_are_user_scoped(tmp_path: Path) -> None:
    client, _ = _harness(tmp_path)
    response = client.post(
        "/api/v1/analysis-runs/run_missing/metrics/calculate",
        headers={"X-User-ID": "other_user"},
        json={"period_end": "2025-12-31"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "run_not_found"
