"""Annual-report upload contract with bounded reads and actionable failures."""

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession, SettingsDependency
from citefin.services.document_parsing import DocumentParsingError, parse_annual_report
from citefin.services.documents import DocumentIngestionError, ingest_annual_report
from citefin.storage import LocalObjectStore

router = APIRouter(prefix="/analysis-runs", tags=["source-documents"])
PdfUpload = Annotated[
    UploadFile,
    File(description="Searchable, unencrypted Chinese annual-report PDF."),
]


class SourceDocumentResponse(BaseModel):
    """Immutable source metadata returned after ingestion or replay."""

    source_id: str
    run_id: str
    document_type: str
    file_name: str
    media_type: str
    sha256: str
    storage_uri: str
    company_name: str | None
    security_code: str | None
    period_end: date | None
    published_at: datetime | None
    language: str
    page_count: int
    text_extractable: bool
    parser_version: str
    ingested_at: datetime
    idempotent_replay: bool
    storage_reused: bool


class DocumentPageResponse(BaseModel):
    """Page-level parse metadata without copying full page text into API state."""

    page_number: int
    text_sha256: str
    text_length: int
    parser_version: str
    bbox_index_uri: str | None
    bbox_index_sha256: str | None
    parse_status: str
    error: dict[str, Any] | None


class DocumentParsingResponse(BaseModel):
    """Deterministic parse outcome for one immutable source document."""

    source_id: str
    page_count: int
    failed_page_count: int
    status: str
    idempotent_replay: bool
    pages: list[DocumentPageResponse]


async def _read_bounded(upload: UploadFile, maximum_bytes: int) -> bytes:
    content = bytearray()
    try:
        while chunk := await upload.read(1024 * 1024):
            content.extend(chunk)
            if len(content) > maximum_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail={
                        "code": "file_too_large",
                        "message": f"PDF exceeds the {maximum_bytes}-byte upload limit.",
                    },
                )
    finally:
        await upload.close()
    return bytes(content)


@router.post(
    "/{run_id}/documents",
    response_model=SourceDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_annual_report(
    run_id: str,
    response: Response,
    session: DatabaseSession,
    settings: SettingsDependency,
    user_id: UserIdHeader,
    file: PdfUpload,
) -> SourceDocumentResponse:
    """Validate and persist one content-addressed annual-report PDF."""

    content = await _read_bounded(file, settings.max_upload_bytes)
    try:
        ingestion = await run_in_threadpool(
            ingest_annual_report,
            session,
            LocalObjectStore(settings.object_storage_root),
            run_id=run_id,
            user_id=user_id,
            file_name=file.filename or "",
            media_type=file.content_type or "",
            content=content,
            min_text_characters=settings.min_pdf_text_characters,
        )
    except DocumentIngestionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if ingestion.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    document = ingestion.document
    return SourceDocumentResponse(
        source_id=document.source_id,
        run_id=document.run_id,
        document_type=document.document_type,
        file_name=document.file_name,
        media_type=document.media_type,
        sha256=document.sha256,
        storage_uri=document.storage_uri,
        company_name=document.company_name,
        security_code=document.security_code,
        period_end=document.period_end,
        published_at=document.published_at,
        language=document.language,
        page_count=document.page_count,
        text_extractable=document.text_extractable,
        parser_version=document.parser_version,
        ingested_at=document.ingested_at,
        idempotent_replay=ingestion.idempotent_replay,
        storage_reused=ingestion.storage_reused,
    )


@router.post(
    "/{run_id}/documents/{source_id}/parse",
    response_model=DocumentParsingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def parse_source_document(
    run_id: str,
    source_id: str,
    response: Response,
    session: DatabaseSession,
    settings: SettingsDependency,
    user_id: UserIdHeader,
) -> DocumentParsingResponse:
    """Extract reproducible page text and coordinate indexes from an owned PDF."""

    try:
        parsing = await run_in_threadpool(
            parse_annual_report,
            session,
            LocalObjectStore(settings.object_storage_root),
            run_id=run_id,
            source_id=source_id,
            user_id=user_id,
            max_pages=settings.max_pdf_pages,
        )
    except DocumentParsingError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if parsing.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return DocumentParsingResponse(
        source_id=source_id,
        page_count=len(parsing.pages),
        failed_page_count=parsing.failed_page_count,
        status="partial_failure" if parsing.failed_page_count else "parsed",
        idempotent_replay=parsing.idempotent_replay,
        pages=[
            DocumentPageResponse(
                page_number=page.page_number,
                text_sha256=page.text_sha256,
                text_length=len(page.text),
                parser_version=page.parser_version,
                bbox_index_uri=page.bbox_index_uri,
                bbox_index_sha256=page.bbox_index_sha256,
                parse_status=page.parse_status,
                error=page.error,
            )
            for page in parsing.pages
        ],
    )
