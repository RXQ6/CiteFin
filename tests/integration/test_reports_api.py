"""F011 report generation API and persistence tests."""

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
    Claim,
    Evidence,
    FinancialFact,
    Report,
    RiskFinding,
    SourceDocument,
    StoredObject,
    VisualizationSpec,
)
from citefin.db.session import build_engine
from citefin.main import create_app


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'reports.db').as_posix()}")
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
            "company_name": "报告示例股份有限公司",
            "security_code": "600005",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def _insert_report_inputs(sessions: sessionmaker[Session], run_id: str) -> None:
    now = datetime.now(UTC)
    with sessions() as session:
        session.add(
            StoredObject(
                sha256="e" * 64,
                storage_uri="object://" + "e" * 64,
                media_type="application/pdf",
                byte_size=1,
                created_at=now,
            )
        )
        session.add(
            SourceDocument(
                source_id="src_report_api",
                run_id=run_id,
                document_type="annual_report",
                file_name="report.pdf",
                media_type="application/pdf",
                sha256="e" * 64,
                storage_uri="object://" + "e" * 64,
                language="zh-CN",
                page_count=1,
                text_extractable=True,
                parser_version="test",
                ingested_at=now,
            )
        )
        session.add(
            FinancialFact(
                fact_id="fact_report_api",
                run_id=run_id,
                source_id="src_report_api",
                statement_type="income_statement",
                concept="revenue",
                label_raw="营业收入",
                period_end=date(2025, 12, 31),
                period_type="duration",
                scope="consolidated",
                currency="CNY",
                display_unit="million_yuan",
                raw_value=Decimal("100"),
                normalized_value=Decimal("100000000"),
                sign_convention="signed_v1",
                page_number=12,
                section="合并利润表",
                row_label="营业收入",
                column_label="2025年",
                extraction_method="manual",
                confidence=Decimal("1"),
                validation_status="extracted",
                mapping_version="financial-fact-v1",
                identity_key="report-api-revenue",
                created_at=now,
            )
        )
        session.add(
            CalculatedMetric(
                metric_id="metric_report_api",
                run_id=run_id,
                metric_code="revenue_growth",
                definition_version="metrics-v1",
                period_end=date(2025, 12, 31),
                input_fact_ids=["fact_report_api"],
                input_snapshot={"revenue": "100000000"},
                value=Decimal("0.1"),
                unit="ratio",
                status="calculated",
                calculator_version="deterministic-decimal-v1",
                calculated_at=now,
            )
        )
        session.add_all(
            [
                Claim(
                    claim_id="claim_report_api_calc",
                    run_id=run_id,
                    claim_type="calculation",
                    text="营业收入增长率为10%。",
                    materiality="major",
                    status="supported",
                    evidence_ids=["ev_report_api_metric"],
                    created_by="financial-analysis-v1",
                    created_at=now,
                ),
                Claim(
                    claim_id="claim_report_api_limit",
                    run_id=run_id,
                    claim_type="limitation",
                    text="报告仅包含已持久化的工程输入。",
                    materiality="minor",
                    status="supported",
                    evidence_ids=["ev_report_api_rule"],
                    created_by="risk-detection-v1",
                    created_at=now,
                ),
                Evidence(
                    evidence_id="ev_report_api_metric",
                    claim_id="claim_report_api_calc",
                    evidence_type="metric",
                    metric_id="metric_report_api",
                    supports="supports",
                    created_at=now,
                ),
                Evidence(
                    evidence_id="ev_report_api_rule",
                    claim_id="claim_report_api_limit",
                    evidence_type="rule",
                    rule_id="R_DATA_LIMITATION_V1",
                    supports="qualifies",
                    created_at=now,
                ),
                RiskFinding(
                    risk_id="risk_report_api",
                    run_id=run_id,
                    risk_code="R_REPORT_API_V1",
                    period_end=date(2025, 12, 31),
                    category="data_quality",
                    severity="low",
                    title="报告输入限制",
                    description="报告输入仅用于契约验证。",
                    claim_ids=["claim_report_api_limit"],
                    status="qualified",
                    limitations=["仅使用合成契约数据。"],
                    confidence=Decimal("0"),
                    created_at=now,
                ),
            ]
        )
        session.commit()


def test_generates_and_replays_structured_report_without_mutating_inputs(
    tmp_path: Path,
) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "report_user", "report-key-1234")
    _insert_report_inputs(sessions, run_id)
    endpoint = f"/api/v1/analysis-runs/{run_id}/reports"

    with sessions() as session:
        before_metric = session.scalar(
            select(CalculatedMetric).where(CalculatedMetric.metric_id == "metric_report_api")
        )
        assert before_metric is not None
        before_value = before_metric.value

    first = client.post(
        endpoint,
        headers={"X-User-ID": "report_user"},
        json={"period_end": "2025-12-31"},
    )
    assert first.status_code == 201
    body = first.json()
    assert body["idempotent_replay"] is False
    assert body["status"] == "candidate"
    assert body["schema_version"] == "financial-report-v2"
    assert set(body["content"]) == {
        "schema_version",
        "run",
        "facts",
        "calculations",
        "inferences",
        "risks",
        "limitations",
        "evidence",
        "visualizations",
    }
    assert body["content"]["calculations"]["metrics"][0]["metric_id"] == "metric_report_api"
    assert body["content"]["facts"][0]["source"]["page_number"] == 12
    assert body["content"]["risks"][0]["risk_id"] == "risk_report_api"
    assert [item["chart_key"] for item in body["content"]["visualizations"]] == [
        "growth_profitability",
        "risk_distribution",
    ]

    visualizations = client.get(
        f"/api/v1/analysis-runs/{run_id}/visualizations",
        headers={"X-User-ID": "report_user"},
        params={"report_id": body["report_id"]},
    )
    assert visualizations.status_code == 200
    specs = visualizations.json()
    assert [item["chart_key"] for item in specs] == [
        "growth_profitability",
        "risk_distribution",
    ]
    assert all(item["status"] == "validated" for item in specs)
    assert all(len(item["data_snapshot_hash"]) == 64 for item in specs)
    forbidden = client.get(
        f"/api/v1/analysis-runs/{run_id}/visualizations",
        headers={"X-User-ID": "other_user"},
    )
    assert forbidden.status_code == 404

    evaluation = client.post(
        f"/api/v1/analysis-runs/{run_id}/evaluations",
        headers={"X-User-ID": "report_user"},
        json={"report_id": body["report_id"]},
    )
    assert evaluation.status_code == 201
    visualization_check = next(
        check for check in evaluation.json()["checks"] if check["code"] == "visualization_integrity"
    )
    assert visualization_check["result"] == "passed"

    replay = client.post(
        endpoint,
        headers={"X-User-ID": "report_user"},
        json={"period_end": "2025-12-31"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["content"] == body["content"]
    with sessions() as session:
        after_metric = session.scalar(
            select(CalculatedMetric).where(CalculatedMetric.metric_id == "metric_report_api")
        )
        assert after_metric is not None
        assert after_metric.value == before_value
        assert session.scalar(select(func.count()).select_from(Report)) == 1
        assert session.scalar(select(func.count()).select_from(VisualizationSpec)) == 2


def test_report_requires_owned_run_and_matching_period(tmp_path: Path) -> None:
    client, sessions = _harness(tmp_path)
    run_id = _create_run(client, "report_user", "report-key-5678")
    _insert_report_inputs(sessions, run_id)
    wrong_period = client.post(
        f"/api/v1/analysis-runs/{run_id}/reports",
        headers={"X-User-ID": "report_user"},
        json={"period_end": "2024-12-31"},
    )
    assert wrong_period.status_code == 422
    assert wrong_period.json()["detail"]["code"] == "report_period_mismatch"
    wrong_user = client.post(
        "/api/v1/analysis-runs/run_missing/reports",
        headers={"X-User-ID": "other_user"},
        json={"period_end": "2025-12-31"},
    )
    assert wrong_user.status_code == 404
    assert wrong_user.json()["detail"]["code"] == "run_not_found"
