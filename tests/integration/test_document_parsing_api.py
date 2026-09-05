"""End-to-end F003 page text, locator, idempotency, and failure tests."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AuditEvent, DocumentPage, StoredObject
from citefin.db.session import build_engine
from citefin.main import create_app
from citefin.services import document_parsing


@dataclass(frozen=True)
class ParsingHarness:
    """An isolated API, database, and object store for parsing tests."""

    client: TestClient
    sessions: sessionmaker[Session]
    storage_root: Path


@pytest.fixture
def parsing_harness(tmp_path: Path) -> Iterator[ParsingHarness]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'parsing.db').as_posix()}")
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
    with TestClient(application) as client:
        yield ParsingHarness(client, sessions, settings.object_storage_root)
    engine.dispose()


def _annual_report_pdf() -> bytes:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    contents = [
        (
            "BT /F1 12 Tf 72 720 Td (Revenue) Tj 200 0 Td (100) Tj "
            "-200 -20 Td (Cost) Tj 200 0 Td (60) Tj ET"
        ),
        (
            "BT /F1 12 Tf 72 720 Td (Assets) Tj 200 0 Td (500) Tj "
            "-200 -20 Td (Liabilities) Tj 200 0 Td (200) Tj ET"
        ),
    ]
    for content in contents:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
        stream = DecodedStreamObject()
        stream.set_data(content.encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _create_and_upload(harness: ParsingHarness, user_id: str = "parse_user") -> tuple[str, str]:
    run = harness.client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": user_id, "Idempotency-Key": f"parse-key-{user_id}"},
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
        headers={"X-User-ID": user_id},
        files={"file": ("annual-report.pdf", _annual_report_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201
    return run_id, str(uploaded.json()["source_id"])


def _parse(harness: ParsingHarness, run_id: str, source_id: str, user_id: str = "parse_user"):
    return harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/parse",
        headers={"X-User-ID": user_id},
    )


def test_parse_persists_page_text_hashes_and_table_locators(
    parsing_harness: ParsingHarness,
) -> None:
    run_id, source_id = _create_and_upload(parsing_harness)

    response = _parse(parsing_harness, run_id, source_id)

    assert response.status_code == 201
    body = response.json()
    assert body["page_count"] == 2
    assert body["failed_page_count"] == 0
    assert body["status"] == "parsed"
    assert [page["page_number"] for page in body["pages"]] == [1, 2]
    assert all(page["parser_version"].endswith("+bbox-v1") for page in body["pages"])
    with parsing_harness.sessions() as session:
        pages = list(session.scalars(select(DocumentPage).order_by(DocumentPage.page_number)))
        assert len(pages) == 2
        assert session.scalar(select(func.count()).select_from(StoredObject)) == 3
        for page in pages:
            assert page.text_sha256 == hashlib.sha256(page.text.encode("utf-8")).hexdigest()
            assert page.bbox_index_sha256 is not None
            index_path = (
                parsing_harness.storage_root
                / page.bbox_index_sha256[:2]
                / f"{page.bbox_index_sha256}.json"
            )
            index = json.loads(index_path.read_text(encoding="utf-8"))
            assert index["page_number"] == page.page_number
            assert index["coordinate_system"]["origin"] == "bottom-left"
            assert index["table_regions"]
            assert len(index["table_regions"][0]["bbox"]) == 4
        event = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "document_parsed"))
        assert event is not None and event.payload["failed_page_count"] == 0


def test_parse_replay_is_idempotent_owner_scoped_and_page_bounded(
    parsing_harness: ParsingHarness,
) -> None:
    run_id, source_id = _create_and_upload(parsing_harness)
    first = _parse(parsing_harness, run_id, source_id)
    replay = _parse(parsing_harness, run_id, source_id)
    wrong_owner = _parse(parsing_harness, run_id, source_id, user_id="another_user")

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["detail"]["code"] == "source_document_not_found"
    with parsing_harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DocumentPage)) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.event_type == "document_parsed")
            )
            == 1
        )

    parsing_harness.client.app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        object_storage_root=parsing_harness.storage_root,
        max_upload_bytes=1024 * 1024,
        min_pdf_text_characters=20,
        max_pdf_pages=1,
    )
    limited_run, limited_source = _create_and_upload(parsing_harness, "limited_user")
    limited = _parse(parsing_harness, limited_run, limited_source, "limited_user")
    assert limited.status_code == 422
    assert limited.json()["detail"]["code"] == "pdf_page_limit_exceeded"


def test_failed_page_is_preserved_as_structured_error(
    parsing_harness: ParsingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, source_id = _create_and_upload(parsing_harness)
    original = document_parsing._extract_page

    def fail_second_page(page: Any, page_number: int):
        if page_number == 2:
            raise RuntimeError("synthetic page failure")
        return original(page, page_number)

    monkeypatch.setattr(document_parsing, "_extract_page", fail_second_page)
    response = _parse(parsing_harness, run_id, source_id)

    assert response.status_code == 201
    assert response.json()["status"] == "partial_failure"
    assert response.json()["failed_page_count"] == 1
    failed = response.json()["pages"][1]
    assert failed["page_number"] == 2
    assert failed["parse_status"] == "failed"
    assert failed["error"] == {
        "code": "PARSER_PAGE_EXTRACTION_FAILED",
        "message": "Page text or locator extraction failed.",
        "exception_type": "RuntimeError",
    }
    with parsing_harness.sessions() as session:
        page = session.get(DocumentPage, (source_id, 2))
        assert page is not None
        assert page.text == ""
        assert page.bbox_index_uri is None
