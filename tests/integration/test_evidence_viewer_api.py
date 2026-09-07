"""F017 report-to-PDF evidence viewer API tests."""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import (
    CalculatedMetric,
    Claim,
    DocumentPage,
    Evidence,
    FinancialFact,
    Report,
    SourceDocument,
    StoredObject,
)
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.storage import LocalObjectStore


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _harness(tmp_path: Path) -> tuple[TestClient, sessionmaker[Session], Settings]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'viewer.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        object_storage_root=tmp_path / "objects",
        max_upload_bytes=1024 * 1024,
        min_pdf_text_characters=1,
    )

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_settings] = lambda: settings
    return TestClient(application), sessions, settings


def _create_run(client: TestClient) -> str:
    response = client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": "viewer_user", "Idempotency-Key": "viewer-run-key"},
        json={
            "company_name": "证据查看示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-11T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return str(response.json()["run_id"])


def _insert_viewer_graph(
    sessions: sessionmaker[Session], settings: Settings, run_id: str
) -> tuple[str, bytes]:
    pdf = _pdf_bytes()
    digest = sha256(pdf).hexdigest()
    stored = LocalObjectStore(settings.object_storage_root).put_pdf(pdf, digest)
    now = datetime.now(UTC)
    with sessions() as session:
        session.add(
            StoredObject(
                sha256=digest,
                storage_uri=stored.storage_uri,
                media_type="application/pdf",
                byte_size=len(pdf),
                created_at=now,
            )
        )
        session.add(
            SourceDocument(
                source_id="src_viewer",
                run_id=run_id,
                document_type="annual_report",
                file_name="证据年报.pdf",
                media_type="application/pdf",
                sha256=digest,
                storage_uri=stored.storage_uri,
                language="zh-CN",
                page_count=1,
                text_extractable=True,
                parser_version="test",
                ingested_at=now,
            )
        )
        session.add(
            DocumentPage(
                source_id="src_viewer",
                page_number=1,
                text="合并利润表 营业收入 100 元",
                text_sha256="a" * 64,
                parser_version="test",
                parse_status="parsed",
                created_at=now,
            )
        )
        session.add(
            FinancialFact(
                fact_id="fact_viewer",
                run_id=run_id,
                source_id="src_viewer",
                statement_type="income_statement",
                concept="revenue",
                label_raw="营业收入",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                period_type="duration",
                scope="consolidated",
                currency="CNY",
                display_unit="yuan",
                raw_value=Decimal("100"),
                normalized_value=Decimal("100"),
                sign_convention="signed_v1",
                page_number=1,
                section="合并利润表",
                table_id="table_1",
                row_label="营业收入",
                column_label="2025年",
                bbox=[1.0, 2.0, 3.0, 4.0],
                extraction_method="manual",
                confidence=Decimal("1"),
                validation_status="extracted",
                mapping_version="financial-fact-v1",
                identity_key="viewer-revenue",
                created_at=now,
            )
        )
        session.add(
            CalculatedMetric(
                metric_id="metric_viewer",
                run_id=run_id,
                metric_code="revenue_growth",
                definition_version="metrics-v1",
                period_end=date(2025, 12, 31),
                input_fact_ids=["fact_viewer"],
                input_snapshot={"revenue": {"fact_id": "fact_viewer", "value": "100"}},
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
                    claim_id="claim_source",
                    run_id=run_id,
                    claim_type="fact",
                    text="营业收入为100元。",
                    materiality="major",
                    status="supported",
                    evidence_ids=["evidence_source"],
                    created_by="test",
                    created_at=now,
                ),
                Claim(
                    claim_id="claim_metric",
                    run_id=run_id,
                    claim_type="calculation",
                    text="收入增长率为10%。",
                    materiality="major",
                    status="supported",
                    evidence_ids=["evidence_metric"],
                    created_by="test",
                    created_at=now,
                ),
                Claim(
                    claim_id="claim_bad_page",
                    run_id=run_id,
                    claim_type="fact",
                    text="该结论的页码已失效。",
                    materiality="minor",
                    status="supported",
                    evidence_ids=["evidence_bad_page"],
                    created_by="test",
                    created_at=now,
                ),
                Claim(
                    claim_id="claim_rule",
                    run_id=run_id,
                    claim_type="limitation",
                    text="该结论仅由规则限定。",
                    materiality="minor",
                    status="supported",
                    evidence_ids=["evidence_rule"],
                    created_by="test",
                    created_at=now,
                ),
                Claim(
                    claim_id="claim_empty",
                    run_id=run_id,
                    claim_type="limitation",
                    text="该结论没有证据。",
                    materiality="minor",
                    status="draft",
                    evidence_ids=[],
                    created_by="test",
                    created_at=now,
                ),
                Evidence(
                    evidence_id="evidence_source",
                    claim_id="claim_source",
                    evidence_type="source_locator",
                    source_id="src_viewer",
                    page_number=1,
                    locator={"section": "合并利润表", "row_label": "营业收入"},
                    excerpt="营业收入 100 元",
                    supports="supports",
                    created_at=now,
                ),
                Evidence(
                    evidence_id="evidence_metric",
                    claim_id="claim_metric",
                    evidence_type="metric",
                    metric_id="metric_viewer",
                    supports="supports",
                    created_at=now,
                ),
                Evidence(
                    evidence_id="evidence_bad_page",
                    claim_id="claim_bad_page",
                    evidence_type="source_locator",
                    source_id="src_viewer",
                    page_number=2,
                    supports="qualifies",
                    created_at=now,
                ),
                Evidence(
                    evidence_id="evidence_rule",
                    claim_id="claim_rule",
                    evidence_type="rule",
                    rule_id="RULE_VIEWER_V1",
                    supports="qualifies",
                    created_at=now,
                ),
            ]
        )
        report_id = "report_viewer"
        session.add(
            Report(
                report_id=report_id,
                run_id=run_id,
                version=1,
                status="candidate",
                schema_version="financial-report-v1",
                content={"schema_version": "financial-report-v1"},
                claim_ids=[
                    "claim_source",
                    "claim_metric",
                    "claim_bad_page",
                    "claim_rule",
                    "claim_empty",
                    "claim_missing",
                ],
                generated_by="test",
                created_at=now,
            )
        )
        session.commit()
    return report_id, pdf


def test_evidence_view_resolves_claims_excerpts_and_pdf_pages(tmp_path: Path) -> None:
    client, sessions, settings = _harness(tmp_path)
    run_id = _create_run(client)
    report_id, _ = _insert_viewer_graph(sessions, settings, run_id)

    response = client.get(
        f"/api/v1/analysis-runs/{run_id}/evidence-view?report_id={report_id}",
        headers={"X-User-ID": "viewer_user"},
    )

    assert response.status_code == 200
    body = response.json()
    claims = {claim["claim_id"]: claim for claim in body["claims"]}
    source = claims["claim_source"]["evidence"][0]["source_pages"][0]
    assert claims["claim_source"]["locator_status"] == "available"
    assert source["file_name"] == "证据年报.pdf"
    assert source["page_number"] == 1
    assert source["excerpt"] == "营业收入 100 元"
    assert source["content_url"].endswith("/documents/src_viewer/content")
    metric_source = claims["claim_metric"]["evidence"][0]["source_pages"][0]
    assert metric_source["excerpt"] == "合并利润表 营业收入 100 元"
    assert body["missing_claim_ids"] == ["claim_missing"]


def test_evidence_view_discloses_missing_and_unavailable_locators(tmp_path: Path) -> None:
    client, sessions, settings = _harness(tmp_path)
    run_id = _create_run(client)
    _insert_viewer_graph(sessions, settings, run_id)

    response = client.get(
        f"/api/v1/analysis-runs/{run_id}/evidence-view",
        headers={"X-User-ID": "viewer_user"},
    )

    assert response.status_code == 200
    claims = {claim["claim_id"]: claim for claim in response.json()["claims"]}
    bad_page = claims["claim_bad_page"]["evidence"][0]["source_pages"][0]
    assert bad_page["status"] == "unavailable"
    assert bad_page["unavailable_reason"] == "page_out_of_range"
    rule = claims["claim_rule"]["evidence"][0]
    assert rule["locator_status"] == "not_applicable"
    assert rule["unavailable_reason"] == "rule_has_no_source_page"
    assert claims["claim_empty"]["unavailable_reason"] == "claim_has_no_evidence"


def test_pdf_content_and_evidence_view_are_user_scoped(tmp_path: Path) -> None:
    client, sessions, settings = _harness(tmp_path)
    run_id = _create_run(client)
    _, pdf = _insert_viewer_graph(sessions, settings, run_id)
    content_url = f"/api/v1/analysis-runs/{run_id}/documents/src_viewer/content"

    content = client.get(content_url, headers={"X-User-ID": "viewer_user"})
    wrong_user_content = client.get(content_url, headers={"X-User-ID": "other_user"})
    wrong_user_view = client.get(
        f"/api/v1/analysis-runs/{run_id}/evidence-view",
        headers={"X-User-ID": "other_user"},
    )

    assert content.status_code == 200
    assert content.content == pdf
    assert content.headers["content-type"] == "application/pdf"
    assert content.headers["cache-control"] == "private, no-store"
    assert "filename*=UTF-8''" in content.headers["content-disposition"]
    assert wrong_user_content.status_code == 404
    assert wrong_user_content.json()["detail"]["code"] == "analysis_run_not_found"
    assert wrong_user_view.status_code == 404
    assert wrong_user_view.json()["detail"]["code"] == "run_not_found"
