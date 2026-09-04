"""End-to-end F002 PDF ingestion and immutable storage tests."""

from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from citefin.api.dependencies import get_database_session
from citefin.config import Settings, get_settings
from citefin.db.base import Base
from citefin.db.models import AuditEvent, SourceDocument, StoredObject
from citefin.db.session import build_engine
from citefin.main import create_app


@dataclass(frozen=True)
class UploadHarness:
    """A test client, database, and isolated object-storage root."""

    client: TestClient
    sessions: sessionmaker[Session]
    storage_root: Path


@pytest.fixture
def upload_harness(tmp_path: Path) -> Iterator[UploadHarness]:
    engine = build_engine(f"sqlite+pysqlite:///{(tmp_path / 'upload.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        object_storage_root=tmp_path / "objects",
        max_upload_bytes=1024 * 1024,
        min_pdf_text_characters=50,
    )

    def override_session() -> Iterator[Session]:
        with sessions() as session:
            yield session

    application = create_app()
    application.dependency_overrides[get_database_session] = override_session
    application.dependency_overrides[get_settings] = lambda: settings
    with TestClient(application) as client:
        yield UploadHarness(
            client=client,
            sessions=sessions,
            storage_root=settings.object_storage_root,
        )
    engine.dispose()


def make_pdf(*, text: str | None = None, encrypted: bool = False) -> bytes:
    """Build a tiny deterministic PDF without external fixture files."""

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    if text is not None:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def create_run(harness: UploadHarness, user_id: str = "upload_user") -> str:
    response = harness.client.post(
        "/api/v1/analysis-runs",
        headers={"X-User-ID": user_id, "Idempotency-Key": f"run-key-{user_id}"},
        json={
            "company_name": "示例股份有限公司",
            "security_code": "600001",
            "report_period_end": "2025-12-31",
            "as_of": "2026-04-01T00:00:00Z",
        },
    )
    assert response.status_code == 201
    return str(response.json()["run_id"])


def upload(
    harness: UploadHarness,
    run_id: str,
    content: bytes,
    *,
    user_id: str = "upload_user",
    file_name: str = "annual-report.pdf",
    media_type: str = "application/pdf",
):
    return harness.client.post(
        f"/api/v1/analysis-runs/{run_id}/documents",
        headers={"X-User-ID": user_id},
        files={"file": (file_name, content, media_type)},
    )


def searchable_pdf() -> bytes:
    return make_pdf(
        text=(
            "Annual Report 2025 Consolidated Balance Sheet Income Statement Cash Flow "
            "Revenue Assets Liabilities Equity Notes and Independent Auditor Report"
        )
    )


def test_upload_persists_metadata_audit_and_content_addressed_object(
    upload_harness: UploadHarness,
) -> None:
    run_id = create_run(upload_harness)

    response = upload(
        upload_harness,
        run_id,
        searchable_pdf(),
        file_name="folder\\annual-report.pdf",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source_id"].startswith("src_")
    assert body["file_name"] == "annual-report.pdf"
    assert body["page_count"] == 1
    assert body["text_extractable"] is True
    assert body["parser_version"].startswith("pypdf-")
    assert body["storage_uri"].startswith("local://sha256/")
    assert body["idempotent_replay"] is False
    assert body["storage_reused"] is False
    object_path = upload_harness.storage_root / body["sha256"][:2] / f"{body['sha256']}.pdf"
    assert object_path.read_bytes() == searchable_pdf()

    with upload_harness.sessions() as session:
        document = session.scalar(select(SourceDocument))
        stored = session.scalar(select(StoredObject))
        event = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "document_uploaded")
        )
        assert document is not None and document.run_id == run_id
        assert stored is not None and stored.sha256 == body["sha256"]
        assert event is not None and event.payload["source_id"] == body["source_id"]


def test_same_run_and_content_replays_original_source(upload_harness: UploadHarness) -> None:
    run_id = create_run(upload_harness)
    content = searchable_pdf()
    first = upload(upload_harness, run_id, content)
    second = upload(upload_harness, run_id, content, file_name="renamed.pdf")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["source_id"] == first.json()["source_id"]
    assert second.json()["file_name"] == "annual-report.pdf"
    assert second.json()["idempotent_replay"] is True
    assert second.json()["storage_reused"] is True
    with upload_harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 1
        assert session.scalar(select(func.count()).select_from(StoredObject)) == 1


def test_different_runs_share_bytes_but_keep_source_ownership(
    upload_harness: UploadHarness,
) -> None:
    first_run = create_run(upload_harness, "user_one")
    second_run = create_run(upload_harness, "user_two")
    content = searchable_pdf()
    first = upload(upload_harness, first_run, content, user_id="user_one")
    second = upload(upload_harness, second_run, content, user_id="user_two")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["source_id"] != second.json()["source_id"]
    assert second.json()["storage_uri"] == first.json()["storage_uri"]
    assert second.json()["storage_reused"] is True
    with upload_harness.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SourceDocument)) == 2
        assert session.scalar(select(func.count()).select_from(StoredObject)) == 1


@pytest.mark.parametrize(
    ("content", "file_name", "media_type", "status_code", "error_code"),
    [
        (make_pdf(), "scan.pdf", "application/pdf", 422, "image_only_pdf"),
        (
            make_pdf(
                text="Encrypted annual report searchable content for rejection",
                encrypted=True,
            ),
            "encrypted.pdf",
            "application/pdf",
            422,
            "encrypted_pdf",
        ),
        (b"%PDF-broken", "broken.pdf", "application/pdf", 422, "unreadable_pdf"),
        (searchable_pdf(), "report.txt", "application/pdf", 422, "invalid_file_extension"),
        (searchable_pdf(), "report.pdf", "text/plain", 415, "unsupported_media_type"),
    ],
)
def test_unsupported_documents_return_actionable_errors(
    upload_harness: UploadHarness,
    content: bytes,
    file_name: str,
    media_type: str,
    status_code: int,
    error_code: str,
) -> None:
    run_id = create_run(upload_harness)

    response = upload(
        upload_harness,
        run_id,
        content,
        file_name=file_name,
        media_type=media_type,
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == error_code


def test_upload_rejects_wrong_owner_and_oversized_file(upload_harness: UploadHarness) -> None:
    run_id = create_run(upload_harness)
    wrong_owner = upload(upload_harness, run_id, searchable_pdf(), user_id="another_user")
    assert wrong_owner.status_code == 404
    assert wrong_owner.json()["detail"]["code"] == "analysis_run_not_found"

    upload_harness.client.app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        object_storage_root=upload_harness.storage_root,
        max_upload_bytes=10,
        min_pdf_text_characters=50,
    )
    oversized = upload(upload_harness, run_id, searchable_pdf())
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "file_too_large"
