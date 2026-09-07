"""F010 risk detection API and persistence tests."""

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
    CalculatedMetric,
    Evidence,
    FinancialFact,
    RiskFinding,
    SourceDocument,
    StoredObject,
)
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.services.metrics import METRIC_DEFINITION_VERSION, METRIC_DEFINITIONS


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'risks.db').as_posix()}")
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
            "company_name": "风险示例股份有限公司",
            "security_code": "600004",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def _insert_metrics(
    sessions: sessionmaker[Session], run_id: str, *, incomplete: bool = False
) -> None:
    now = datetime.now(UTC)
    values = {definition.code: Decimal("1") for definition in METRIC_DEFINITIONS}
    values.update(
        {
            "revenue_growth": Decimal("-0.1"),
            "accounts_receivable_growth": Decimal("0.2"),
            "inventory_growth": Decimal("0.0"),
            "debt_to_assets": Decimal("0.8"),
            "current_ratio": Decimal("0.8"),
            "interest_coverage": Decimal("1.2"),
            "cash_to_short_debt": Decimal("0.5"),
        }
    )
    with sessions() as session:
        session.add(
            StoredObject(
                sha256="d" * 64,
                storage_uri="object://" + "d" * 64,
                media_type="application/pdf",
                byte_size=1,
                created_at=now,
            )
        )
        session.add(
            SourceDocument(
                source_id="src_risk",
                run_id=run_id,
                document_type="annual_report",
                file_name="risk.pdf",
                media_type="application/pdf",
                sha256="d" * 64,
                storage_uri="object://" + "d" * 64,
                language="zh-CN",
                page_count=1,
                text_extractable=True,
                parser_version="test",
                ingested_at=now,
            )
        )
        for definition in METRIC_DEFINITIONS:
            fact_id = f"fact_risk_{definition.code}"
            session.add(
                FinancialFact(
                    fact_id=fact_id,
                    run_id=run_id,
                    source_id="src_risk",
                    statement_type="income_statement",
                    concept=definition.input_concepts[0],
                    label_raw=definition.name_zh,
                    period_end=date(2025, 12, 31),
                    period_type="duration",
                    scope="consolidated",
                    currency="CNY",
                    display_unit="yuan",
                    raw_value=Decimal("1"),
                    normalized_value=Decimal("1"),
                    sign_convention="signed_v1",
                    page_number=1,
                    section="synthetic",
                    row_label=definition.name_zh,
                    column_label="2025",
                    extraction_method="manual",
                    confidence=Decimal("1"),
                    validation_status="extracted",
                    mapping_version="financial-fact-v1",
                    identity_key=f"risk-{definition.code}",
                    created_at=now,
                )
            )
            status = (
                "zero_denominator"
                if incomplete and definition.code == "interest_coverage"
                else "calculated"
            )
            session.add(
                CalculatedMetric(
                    metric_id=f"metric_risk_{definition.code}",
                    run_id=run_id,
                    metric_code=definition.code,
                    definition_version=METRIC_DEFINITION_VERSION,
                    period_end=date(2025, 12, 31),
                    input_fact_ids=[fact_id],
                    input_snapshot={},
                    value=None if status != "calculated" else values[definition.code],
                    unit=definition.unit,
                    status=status,
                    reason="zero_denominator:interest_expense" if status != "calculated" else None,
                    calculator_version="test-calculator",
                    calculated_at=now,
                )
            )
        session.commit()


def test_detects_persists_and_replays_evidence_backed_risks(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "risk_user", "risk-key-1234")
    _insert_metrics(sessions, run_id)
    endpoint = f"/api/v1/analysis-runs/{run_id}/risk-detection"

    first = client.post(
        endpoint,
        headers={"X-User-ID": "risk_user"},
        json={"period_end": "2025-12-31"},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["idempotent_replay"] is False
    assert len(body["findings"]) == 6
    high_findings = [finding for finding in body["findings"] if finding["severity"] == "high"]
    assert high_findings
    assert all(finding["claim_ids"] for finding in high_findings)
    with sessions() as session:
        for finding in high_findings:
            evidence_types = {
                evidence.evidence_type
                for evidence in session.scalars(
                    select(Evidence).where(Evidence.claim_id.in_(finding["claim_ids"]))
                )
            }
            assert "fact" in evidence_types
            assert "rule" in evidence_types or "metric" in evidence_types

    replay = client.post(
        endpoint,
        headers={"X-User-ID": "risk_user"},
        json={"period_end": "2025-12-31"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["findings"] == body["findings"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(RiskFinding)) == 6


def test_insufficient_metric_data_is_qualified_and_scoped(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "risk_user", "risk-key-5678")
    _insert_metrics(sessions, run_id, incomplete=True)

    response = client.post(
        f"/api/v1/analysis-runs/{run_id}/risk-detection",
        headers={"X-User-ID": "risk_user"},
        json={"period_end": "2025-12-31"},
    )

    assert response.status_code == 201
    data_quality = next(
        finding for finding in response.json()["findings"] if finding["category"] == "data_quality"
    )
    assert data_quality["status"] == "qualified"
    assert data_quality["confidence"] == "0.0000"
    assert any("interest_coverage" in item for item in data_quality["limitations"])
    assert not any(
        finding["risk_code"] == "R_INTEREST_COVERAGE_BELOW_1_5_V1"
        for finding in response.json()["findings"]
    )


def test_risk_detection_requires_owned_run_and_complete_metrics(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "risk_user", "risk-key-9012")
    missing_metrics = client.post(
        f"/api/v1/analysis-runs/{run_id}/risk-detection",
        headers={"X-User-ID": "risk_user"},
        json={"period_end": "2025-12-31"},
    )
    assert missing_metrics.status_code == 422
    assert missing_metrics.json()["detail"]["code"] == "incomplete_metric_set"
    wrong_user = client.post(
        "/api/v1/analysis-runs/run_missing/risk-detection",
        headers={"X-User-ID": "other_user"},
        json={"period_end": "2025-12-31"},
    )
    assert wrong_user.status_code == 404
    assert wrong_user.json()["detail"]["code"] == "run_not_found"
    assert sessions is not None
