"""Validation and atomic metadata ingestion for annual-report PDFs."""

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

import pypdf
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from citefin.db.models import AnalysisRun, AuditEvent, SourceDocument, StoredObject
from citefin.ids import new_prefixed_id
from citefin.storage import LocalObjectStore, StorageIntegrityError


class DocumentIngestionError(ValueError):
    """A stable, actionable failure safe to expose at the API boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class PdfInspection:
    """Deterministic properties required before accepting a PDF."""

    sha256: str
    page_count: int
    text_characters: int
    parser_version: str


@dataclass(frozen=True)
class DocumentIngestion:
    """A new or replayed source-document result."""

    document: SourceDocument
    idempotent_replay: bool
    storage_reused: bool


def inspect_pdf(content: bytes, min_text_characters: int) -> PdfInspection:
    """Reject malformed, encrypted, empty, or image-only PDF input."""

    if not content.startswith(b"%PDF-"):
        raise DocumentIngestionError("invalid_pdf_signature", "File content is not a PDF.")
    digest = hashlib.sha256(content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted:
            raise DocumentIngestionError(
                "encrypted_pdf", "Encrypted PDFs are not supported in the MVP."
            )
        page_count = len(reader.pages)
        text_characters = sum(
            len("".join((page.extract_text() or "").split())) for page in reader.pages
        )
    except DocumentIngestionError:
        raise
    except (PdfReadError, OSError, ValueError) as error:
        raise DocumentIngestionError(
            "unreadable_pdf", "The PDF is malformed or cannot be parsed."
        ) from error
    if page_count == 0:
        raise DocumentIngestionError("empty_pdf", "The PDF contains no pages.")
    if text_characters < min_text_characters:
        raise DocumentIngestionError(
            "image_only_pdf",
            "The PDF does not contain enough searchable text; OCR is outside the MVP.",
        )
    return PdfInspection(
        sha256=digest,
        page_count=page_count,
        text_characters=text_characters,
        parser_version=f"pypdf-{pypdf.__version__}",
    )


def _safe_file_name(file_name: str) -> str:
    normalized = PurePosixPath(file_name.replace("\\", "/")).name.strip()
    if not normalized or len(normalized) > 255:
        raise DocumentIngestionError(
            "invalid_file_name", "A PDF file name between 1 and 255 characters is required."
        )
    if not normalized.lower().endswith(".pdf"):
        raise DocumentIngestionError("invalid_file_extension", "File name must end in .pdf.")
    return normalized


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.run_id == run_id,
            AnalysisRun.user_id == user_id,
        )
    )
    if run is None:
        raise DocumentIngestionError(
            "analysis_run_not_found", "Analysis run was not found.", status_code=404
        )
    return run


def ingest_annual_report(
    session: Session,
    store: LocalObjectStore,
    *,
    run_id: str,
    user_id: str,
    file_name: str,
    media_type: str,
    content: bytes,
    min_text_characters: int,
) -> DocumentIngestion:
    """Validate, store, and link one annual report without duplicating its bytes."""

    if media_type != "application/pdf":
        raise DocumentIngestionError(
            "unsupported_media_type", "Only application/pdf uploads are supported.", 415
        )
    safe_name = _safe_file_name(file_name)
    _owned_run(session, run_id, user_id)
    inspection = inspect_pdf(content, min_text_characters)
    existing = session.scalar(
        select(SourceDocument).where(
            SourceDocument.run_id == run_id,
            SourceDocument.sha256 == inspection.sha256,
        )
    )
    if existing is not None:
        return DocumentIngestion(document=existing, idempotent_replay=True, storage_reused=True)

    try:
        stored = store.put_pdf(content, inspection.sha256)
    except StorageIntegrityError as error:
        raise DocumentIngestionError(
            "storage_integrity_error", "Stored object failed integrity verification.", 500
        ) from error

    if session.get(StoredObject, inspection.sha256) is None:
        try:
            with session.begin_nested():
                session.add(
                    StoredObject(
                        sha256=inspection.sha256,
                        storage_uri=stored.storage_uri,
                        media_type=media_type,
                        byte_size=len(content),
                        created_at=datetime.now(UTC),
                    )
                )
                session.flush()
        except IntegrityError:
            if session.get(StoredObject, inspection.sha256) is None:
                raise

    now = datetime.now(UTC)
    source_id = new_prefixed_id("src")
    document = SourceDocument(
        source_id=source_id,
        run_id=run_id,
        document_type="annual_report",
        file_name=safe_name,
        media_type=media_type,
        sha256=inspection.sha256,
        storage_uri=stored.storage_uri,
        language="zh-CN",
        page_count=inspection.page_count,
        text_extractable=True,
        parser_version=inspection.parser_version,
        ingested_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="document_ingest",
        event_type="document_uploaded",
        status="success",
        payload={
            "source_id": source_id,
            "sha256": inspection.sha256,
            "page_count": inspection.page_count,
            "storage_reused": not stored.created,
        },
        created_at=now,
    )
    session.add_all([document, event])
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(SourceDocument).where(
                SourceDocument.run_id == run_id,
                SourceDocument.sha256 == inspection.sha256,
            )
        )
        if concurrent is None:
            raise
        return DocumentIngestion(document=concurrent, idempotent_replay=True, storage_reused=True)

    return DocumentIngestion(
        document=document,
        idempotent_replay=False,
        storage_reused=not stored.created,
    )
