"""End-to-end F004 consolidated-statement identification tests."""

from collections.abc import Iterator
from dataclasses import dataclass
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
from citefin.db.models import AuditEvent, StatementIdentification
from citefin.db.session import build_engine
from citefin.main import create_app


@dataclass(frozen=True)
class StatementHarness:
    client: TestClient
    sessions: sessionmaker[Session]


def _statement_pdf(titles: list[str]) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for title in titles:
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


def _harness(tmp_path: Path) -> StatementHarness:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'statements.db').as_posix()}")
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
    client = TestClient(application)
    return StatementHarness(client=client, sessions=sessions)


def _run_and_parse(harness: StatementHarness, titles: list[str]) -> tuple[str, str]:
    run = harness.client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": "statement_user", "Idempotency-Key": "statement-key"},
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
        headers={"X-User-ID": "statement_user"},
        files={"file": ("annual-report.pdf", _statement_pdf(titles), "application/pdf")},
    )
    assert uploaded.status_code == 201
    source_id = str(uploaded.json()["source_id"])
    parsed = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/parse",
        headers={"X-User-ID": "statement_user"},
    )
    assert parsed.status_code == 201
    return run_id, source_id


def test_identifies_three_consolidated_statements_with_period_and_locator(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    run_id, source_id = _run_and_parse(
        harness,
        [
            "Consolidated Balance Sheet 2025-12-31",
            "Consolidated Income Statement 2025-12-31",
            "Consolidated Cash Flow Statement 2025-12-31",
        ],
    )

    response = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/statements",
        headers={"X-User-ID": "statement_user"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "located"
    assert body["idempotent_replay"] is False
    assert {item["statement_type"] for item in body["statements"]} == {
        "balance_sheet",
        "income_statement",
        "cashflow_statement",
    }
    assert all(item["status"] == "located" for item in body["statements"])
    assert all(item["scope"] == "consolidated" for item in body["statements"])
    assert all(item["period_end"] == "2025-12-31" for item in body["statements"])
    assert [item["page_number"] for item in body["statements"]] == [1, 2, 3]
    assert all(item["table_id"] == "table_candidate_1" for item in body["statements"])
    assert all(item["locator"]["bbox_index_sha256"] for item in body["statements"])

    replay = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/statements",
        headers={"X-User-ID": "statement_user"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    with harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(StatementIdentification)) == 3
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "statements_identified")
            )
            == 1
        )


def test_parent_only_candidates_do_not_satisfy_consolidated_requirement(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id, source_id = _run_and_parse(
        harness,
        [
            "Parent Company Balance Sheet 2025-12-31",
            "Consolidated Income Statement 2025-12-31",
            "Consolidated Cash Flow Statement 2025-12-31",
        ],
    )
    response = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/statements",
        headers={"X-User-ID": "statement_user"},
    )

    assert response.status_code == 201
    body = response.json()
    balance = next(item for item in body["statements"] if item["statement_type"] == "balance_sheet")
    assert body["status"] == "partial"
    assert balance["status"] == "missing"
    assert balance["scope"] == "parent"
    assert balance["reason"]["code"] == "only_parent_statement_found"


def test_ambiguous_scope_requires_user_confirmation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run_id, source_id = _run_and_parse(
        harness,
        [
            "Balance Sheet 2025-12-31",
            "Consolidated Income Statement 2025-12-31",
            "Consolidated Cash Flow Statement 2025-12-31",
        ],
    )
    response = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/statements",
        headers={"X-User-ID": "statement_user"},
    )

    assert response.status_code == 201
    body = response.json()
    balance = next(item for item in body["statements"] if item["statement_type"] == "balance_sheet")
    assert body["status"] == "awaiting_user"
    assert balance["status"] == "ambiguous"
    assert balance["reason"]["code"] == "consolidated_scope_not_explicit"


def test_statement_identification_requires_complete_document_parse(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    run = harness.client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": "statement_user", "Idempotency-Key": "unparsed-key"},
        json={
            "company_name": "示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-01T00:00:00Z",
        },
    )
    run_id = str(run.json()["run_id"])
    uploaded = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents",
        headers={"X-User-ID": "statement_user"},
        files={
            "file": (
                "annual-report.pdf",
                _statement_pdf(["Consolidated Balance Sheet 2025-12-31"] * 3),
                "application/pdf",
            )
        },
    )
    source_id = str(uploaded.json()["source_id"])
    response = harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/statements",
        headers={"X-User-ID": "statement_user"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "document_not_parsed"
