"""Read-only workbench API integration tests."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.db.base import Base
from citefin.db.models import (
    CalculatedMetric,
    Claim,
    Evaluation,
    FinancialFact,
    GoalGateDecision,
    Report,
    RiskFinding,
    SourceDocument,
    StatementIdentification,
    StoredObject,
)
from citefin.db.session import build_engine
from citefin.main import create_app


@pytest.fixture
def workbench_harness(tmp_path: Path) -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'workbench.db').as_posix()}")
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


def _create_run(client: TestClient, user_id: str, key: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": user_id, "Idempotency-Key": key},
        json={
            "company_name": "工作台示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return response.json()


def _seed_projection(session: Session, run_id: str) -> None:
    now = datetime.now(UTC)
    source_id = "src_workbench"
    fact_id = "fact_workbench"
    metric_id = "metric_workbench"
    claim_id = "claim_workbench"
    report_id = "report_workbench"
    evaluation_id = "eval_workbench"
    session.add_all(
        [
            StoredObject(
                sha256="a" * 64,
                storage_uri="sha256/aa/workbench.pdf",
                media_type="application/pdf",
                byte_size=100,
                created_at=now,
            ),
            SourceDocument(
                source_id=source_id,
                run_id=run_id,
                document_type="annual_report",
                file_name="示例年报.pdf",
                media_type="application/pdf",
                sha256="a" * 64,
                storage_uri="sha256/aa/workbench.pdf",
                company_name="工作台示例股份有限公司",
                security_code="600001",
                period_end=date(2025, 12, 31),
                published_at=None,
                language="zh-CN",
                page_count=3,
                text_extractable=True,
                parser_version="pypdf-test",
                ingested_at=now,
            ),
            StatementIdentification(
                statement_id="statement_workbench",
                source_id=source_id,
                statement_type="balance_sheet",
                status="located",
                title="合并资产负债表",
                scope="consolidated",
                period_end=date(2025, 12, 31),
                page_number=1,
                table_id="table-1",
                locator={"section": "合并资产负债表"},
                candidate_count=1,
                candidates=[],
                reason=None,
                algorithm_version="statement-test",
                created_at=now,
                updated_at=now,
            ),
            FinancialFact(
                fact_id=fact_id,
                run_id=run_id,
                source_id=source_id,
                statement_type="balance_sheet",
                concept="total_assets",
                label_raw="资产总计",
                period_start=None,
                period_end=date(2025, 12, 31),
                period_type="instant",
                scope="consolidated",
                currency="CNY",
                display_unit="yuan",
                raw_value=Decimal("100"),
                normalized_value=Decimal("100"),
                sign_convention="reported-sign-v1",
                page_number=1,
                section="合并资产负债表",
                table_id="table-1",
                row_label="资产总计",
                column_label="2025年末",
                bbox=None,
                extraction_method="manual",
                confidence=Decimal("1"),
                validation_status="extracted",
                mapping_version="mapping-test",
                identity_key="asset-2025",
                conflict_group_id=None,
                created_at=now,
            ),
            CalculatedMetric(
                metric_id=metric_id,
                run_id=run_id,
                metric_code="debt_to_assets",
                definition_version="metric-test",
                period_end=date(2025, 12, 31),
                input_fact_ids=[fact_id],
                input_snapshot={"total_assets": {"fact_id": fact_id, "value": "100"}},
                value=Decimal("0.4"),
                unit="ratio",
                status="calculated",
                reason=None,
                calculator_version="calculator-test",
                calculated_at=now,
            ),
            Claim(
                claim_id=claim_id,
                run_id=run_id,
                claim_type="calculation",
                text="资产负债率为 40%。",
                materiality="major",
                status="supported",
                evidence_ids=[],
                created_by="workbench-test",
                created_at=now,
            ),
            RiskFinding(
                risk_id="risk_workbench",
                run_id=run_id,
                risk_code="risk-test",
                period_end=date(2025, 12, 31),
                category="solvency",
                severity="low",
                title="偿债风险观察",
                description="基于已持久化指标的测试风险。",
                claim_ids=[claim_id],
                status="open",
                limitations=[],
                confidence=Decimal("0.8"),
                created_at=now,
            ),
            Report(
                report_id=report_id,
                run_id=run_id,
                version=1,
                status="candidate",
                schema_version="financial-report-v1",
                content={"schema_version": "financial-report-v1"},
                claim_ids=[claim_id],
                generated_by="report-test",
                created_at=now,
            ),
            Evaluation(
                evaluation_id=evaluation_id,
                run_id=run_id,
                report_id=report_id,
                evaluator_version="evaluator-test",
                status="passed",
                checks=[{"code": "report_schema", "result": "passed"}],
                blocking_reasons=[],
                input_snapshot={"report_id": report_id},
                node_hint=None,
                repair_instruction=None,
                created_at=now,
            ),
            GoalGateDecision(
                gate_id="gate_workbench",
                run_id=run_id,
                report_id=report_id,
                evaluation_id=evaluation_id,
                gate_version="gate-test",
                decision="revision_required",
                evidence_refs=[],
                blocking_reasons=[{"code": "external_review_pending"}],
                node_hint="write_report",
                repair_instruction="完成所需复核。",
                created_at=now,
            ),
        ]
    )
    session.commit()


def test_workbench_lists_owned_runs_and_complete_persisted_projection(
    workbench_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = workbench_harness
    owned = _create_run(client, "workbench_user", "workbench-owned-key")
    _create_run(client, "other_user", "workbench-other-key")
    with sessions() as session:
        _seed_projection(session, str(owned["run_id"]))

    runs = client.get("/api/v1/analysis-runs", headers={"X-User-ID": "workbench_user"})
    workspace = client.get(
        f"/api/v1/analysis-runs/{owned['run_id']}/workspace",
        headers={"X-User-ID": "workbench_user"},
    )

    assert runs.status_code == 200
    assert [item["run_id"] for item in runs.json()] == [owned["run_id"]]
    assert workspace.status_code == 200
    body = workspace.json()
    assert body["run"]["company_name"] == "工作台示例股份有限公司"
    assert body["sources"][0]["file_name"] == "示例年报.pdf"
    assert body["statements"][0]["page_number"] == 1
    assert body["facts"][0]["concept"] == "total_assets"
    assert body["metrics"][0]["value"] == "0.4000000000000000"
    assert body["claims"][0]["claim_id"] == "claim_workbench"
    assert body["risks"][0]["severity"] == "low"
    assert body["reports"][0]["report_id"] == "report_workbench"
    assert body["evaluations"][0]["status"] == "passed"
    assert body["gate_decisions"][0]["decision"] == "revision_required"
    assert body["checkpoints"][0]["state_version"] == 1
    assert "storage_uri" not in workspace.text
    assert "state_data" not in workspace.text


def test_workbench_empty_state_limits_and_user_isolation(
    workbench_harness: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = workbench_harness
    owned = _create_run(client, "workbench_user", "workbench-empty-key")
    empty = client.get(
        f"/api/v1/analysis-runs/{owned['run_id']}/workspace",
        headers={"X-User-ID": "workbench_user"},
    )
    hidden = client.get(
        f"/api/v1/analysis-runs/{owned['run_id']}/workspace",
        headers={"X-User-ID": "other_user"},
    )
    invalid_limit = client.get(
        "/api/v1/analysis-runs?limit=0", headers={"X-User-ID": "workbench_user"}
    )

    assert empty.status_code == 200
    assert empty.json()["sources"] == []
    assert empty.json()["metrics"] == []
    assert hidden.status_code == 404
    assert hidden.json()["detail"]["code"] == "run_not_found"
    assert invalid_limit.status_code == 422
