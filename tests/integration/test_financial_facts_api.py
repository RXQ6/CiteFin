"""End-to-end F005 normalization tests using a synthetic F004-linked report."""

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import FinancialFact
from citefin.db.session import build_engine
from citefin.main import create_app


@dataclass(frozen=True)
class FactHarness:
    client: TestClient
    sessions: sessionmaker[Session]


def _pdf() -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for title in (
        "Consolidated Balance Sheet 2025-12-31",
        "Consolidated Income Statement 2025-12-31",
        "Consolidated Cash Flow Statement 2025-12-31",
    ):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(
            (
                "BT /F1 12 Tf 72 720 Td ("
                f"{title}"
                ") Tj 200 0 Td (500) Tj -200 -20 Td (Total) Tj 200 0 Td (400) Tj ET"
            ).encode("ascii")
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _harness(tmp_path: Path) -> FactHarness:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'facts.db').as_posix()}")
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
    return FactHarness(client=TestClient(application), sessions=sessions)


def _prepared(harness: FactHarness) -> tuple[str, str]:
    headers = {"X-User-ID": "fact_user", "Idempotency-Key": "fact-key-1234"}
    run = harness.client.post(
        "/api/v1/analysis-runs",
        headers=headers,
        json={
            "company_name": "示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-01T00:00:00Z",
        },
    )
    assert run.status_code == 201
    run_id = str(run.json()["run_id"])
    uploaded = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents",
        headers={"X-User-ID": "fact_user"},
        files={"file": ("annual-report.pdf", _pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    source_id = str(uploaded.json()["source_id"])
    parsed = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/parse",
        headers={"X-User-ID": "fact_user"},
    )
    assert parsed.status_code == 201
    identified = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/statements",
        headers={"X-User-ID": "fact_user"},
    )
    assert identified.status_code == 201
    assert identified.json()["status"] == "located"
    return run_id, source_id


def _payload(raw_value: str = "12.50", label: str = "营业收入") -> dict[str, object]:
    return {
        "statement_type": "income_statement",
        "raw_label": label,
        "raw_value": raw_value,
        "period_end": "2025-12-31",
        "period_type": "duration",
        "period_start": "2025-01-01",
        "scope": "consolidated",
        "currency": "CNY",
        "display_unit": "million_yuan",
        "page_number": 2,
        "section": "合并利润表",
        "table_id": "table_candidate_1",
        "row_label": label,
        "column_label": "本期金额",
        "bbox": [1.0, 2.0, 3.0, 4.0],
        "extraction_method": "manual",
        "confidence": "1.0",
    }


def test_normalizes_decimal_value_and_replays_idempotently(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id, source_id = _prepared(harness)
    endpoint = f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/facts/normalize"
    headers = {"X-User-ID": "fact_user"}

    response = harness.client.post(endpoint, headers=headers, json=_payload())
    assert response.status_code == 201
    body = response.json()
    assert body["concept"] == "revenue"
    assert Decimal(body["raw_value"]) == Decimal("12.50")
    assert Decimal(body["normalized_value"]) == Decimal("12500000.00")
    assert body["validation_status"] == "extracted"
    assert body["idempotent_replay"] is False

    replay = harness.client.post(endpoint, headers=headers, json=_payload())
    assert replay.status_code == 200
    assert replay.json()["fact_id"] == body["fact_id"]
    assert replay.json()["idempotent_replay"] is True
    with harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(FinancialFact)) == 1


def test_conflicting_identity_is_preserved_as_conflict(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id, source_id = _prepared(harness)
    endpoint = f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/facts/normalize"
    headers = {"X-User-ID": "fact_user"}

    first = harness.client.post(endpoint, headers=headers, json=_payload("12.50"))
    assert first.status_code == 201
    second = harness.client.post(endpoint, headers=headers, json=_payload("13.50"))
    assert second.status_code == 201
    assert second.json()["validation_status"] == "conflict"
    assert second.json()["conflict_group_id"]
    with harness.sessions() as session:
        facts = list(session.scalars(select(FinancialFact).order_by(FinancialFact.created_at)))
        assert len(facts) == 2
        assert {fact.validation_status for fact in facts} == {"conflict"}


def test_unknown_label_is_rejected_without_persisting_a_fact(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id, source_id = _prepared(harness)
    endpoint = f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/facts/normalize"
    response = harness.client.post(
        endpoint,
        headers={"X-User-ID": "fact_user"},
        json=_payload(label="未知财务项目"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unmapped_label"
    with harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(FinancialFact)) == 0
