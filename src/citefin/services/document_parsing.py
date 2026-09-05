"""Deterministic page text and locator extraction for accepted annual-report PDFs."""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pypdf
from pypdf import PdfReader
from pypdf._page import PageObject
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    DocumentPage,
    SourceDocument,
    StoredObject,
)
from citefin.ids import new_prefixed_id
from citefin.storage import LocalObjectStore, StorageIntegrityError

PARSER_VERSION = f"pypdf-{pypdf.__version__}+bbox-v1"
BBOX_MEDIA_TYPE = "application/vnd.citefin.bbox-index+json"


class DocumentParsingError(ValueError):
    """A stable document-parse failure safe to expose through the API."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ParsedPage:
    """One page's extracted text and canonical coordinate-index bytes."""

    text: str
    text_sha256: str
    bbox_index: bytes
    bbox_index_sha256: str


@dataclass(frozen=True)
class DocumentParsing:
    """A new or replayed page-level parse result."""

    pages: list[DocumentPage]
    idempotent_replay: bool

    @property
    def failed_page_count(self) -> int:
        return sum(page.parse_status == "failed" for page in self.pages)


def _number(value: Any) -> float:
    return round(float(value), 3)


def _transformed_origin(current_matrix: Any, text_matrix: Any) -> tuple[float, float]:
    if len(current_matrix) < 6 or len(text_matrix) < 6:
        raise ValueError("PDF text matrix is incomplete")
    return (
        float(text_matrix[4]) * float(current_matrix[0])
        + float(text_matrix[5]) * float(current_matrix[2])
        + float(current_matrix[4]),
        float(text_matrix[4]) * float(current_matrix[1])
        + float(text_matrix[5]) * float(current_matrix[3])
        + float(current_matrix[5]),
    )


def _table_regions(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[list[dict[str, Any]]] = []
    for block in sorted(blocks, key=lambda item: (-item["bbox"][1], item["bbox"][0])):
        center_y = (block["bbox"][1] + block["bbox"][3]) / 2
        matching = next(
            (
                row
                for row in rows
                if abs(
                    center_y
                    - sum((item["bbox"][1] + item["bbox"][3]) / 2 for item in row) / len(row)
                )
                <= 3
            ),
            None,
        )
        if matching is None:
            rows.append([block])
        else:
            matching.append(block)

    def is_table_row(row: list[dict[str, Any]]) -> bool:
        if len(row) >= 2 and (
            max(item["bbox"][0] for item in row) - min(item["bbox"][0] for item in row) >= 20
        ):
            return True
        combined = " ".join(str(item["text"]) for item in row)
        return bool(re.search(r"\d", combined) and re.search(r"[^\W\d_]", combined))

    table_rows = [
        sorted(row, key=lambda item: item["bbox"][0]) for row in rows if is_table_row(row)
    ]
    if len(table_rows) < 2:
        return []
    all_blocks = [block for row in table_rows for block in row]
    bbox = [
        min(block["bbox"][0] for block in all_blocks),
        min(block["bbox"][1] for block in all_blocks),
        max(block["bbox"][2] for block in all_blocks),
        max(block["bbox"][3] for block in all_blocks),
    ]
    return [
        {
            "table_id": "table_candidate_1",
            "bbox": [_number(value) for value in bbox],
            "row_count": len(table_rows),
            "column_count": max(2 if len(row) == 1 else len(row) for row in table_rows),
            "block_ids": [[block["block_id"] for block in row] for row in table_rows],
            "detection_method": "aligned_text_rows_v1",
        }
    ]


def _extract_page(page: PageObject, page_number: int) -> ParsedPage:
    blocks: list[dict[str, Any]] = []
    page_width = _number(page.mediabox.width)
    page_height = _number(page.mediabox.height)

    def visitor(
        text: str,
        current_matrix: Any,
        text_matrix: Any,
        _font_dictionary: Any,
        font_size: float,
    ) -> None:
        visible = text.strip()
        if not visible:
            return
        size = max(abs(float(font_size)), 1.0)
        origin_x, origin_y = _transformed_origin(current_matrix, text_matrix)
        x0 = min(page_width, max(0.0, origin_x))
        baseline = min(page_height, max(0.0, origin_y))
        x1 = min(page_width, x0 + max(len(visible) * size * 0.5, size * 0.5))
        y0 = max(0.0, baseline - size * 0.2)
        y1 = min(page_height, baseline + size * 0.8)
        blocks.append(
            {
                "block_id": f"text_{len(blocks) + 1}",
                "text": visible,
                "bbox": [_number(x0), _number(y0), _number(x1), _number(y1)],
            }
        )

    text = page.extract_text(visitor_text=visitor) or ""
    index = {
        "schema_version": "bbox-index-v1",
        "page_number": page_number,
        "coordinate_system": {
            "origin": "bottom-left",
            "unit": "pdf-point",
            "width": page_width,
            "height": page_height,
            "bbox_method": "transformed_text_matrix_estimate_v1",
        },
        "text_blocks": blocks,
        "table_regions": _table_regions(blocks),
    }
    index_bytes = json.dumps(
        index, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return ParsedPage(
        text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        bbox_index=index_bytes,
        bbox_index_sha256=hashlib.sha256(index_bytes).hexdigest(),
    )


def _owned_document(session: Session, run_id: str, source_id: str, user_id: str) -> SourceDocument:
    document = session.scalar(
        select(SourceDocument)
        .join(AnalysisRun)
        .where(
            SourceDocument.source_id == source_id,
            SourceDocument.run_id == run_id,
            AnalysisRun.user_id == user_id,
        )
    )
    if document is None:
        raise DocumentParsingError(
            "source_document_not_found", "Source document was not found.", 404
        )
    return document


def _existing_pages(session: Session, source_id: str) -> list[DocumentPage]:
    return list(
        session.scalars(
            select(DocumentPage)
            .where(DocumentPage.source_id == source_id)
            .order_by(DocumentPage.page_number)
        )
    )


def parse_annual_report(
    session: Session,
    store: LocalObjectStore,
    *,
    run_id: str,
    source_id: str,
    user_id: str,
    max_pages: int,
) -> DocumentParsing:
    """Persist page text, locator indexes, and per-page failures exactly once."""

    document = _owned_document(session, run_id, source_id, user_id)
    existing = _existing_pages(session, source_id)
    if existing:
        if len(existing) == document.page_count and all(
            page.parser_version == PARSER_VERSION for page in existing
        ):
            return DocumentParsing(pages=existing, idempotent_replay=True)
        raise DocumentParsingError(
            "parse_state_conflict",
            "Existing page records do not form a complete parse for this parser version.",
            409,
        )
    if document.page_count > max_pages:
        raise DocumentParsingError(
            "pdf_page_limit_exceeded",
            f"PDF contains more than the configured {max_pages}-page parsing limit.",
            422,
        )

    try:
        content = store.read_pdf(document.sha256, document.storage_uri)
        reader = PdfReader(io.BytesIO(content), strict=False)
    except (StorageIntegrityError, PdfReadError, OSError, ValueError) as error:
        raise DocumentParsingError(
            "source_integrity_error",
            "The immutable source PDF is unavailable or failed integrity verification.",
            500,
        ) from error
    if reader.is_encrypted:
        raise DocumentParsingError("encrypted_pdf", "Encrypted PDFs cannot be parsed.")
    if len(reader.pages) != document.page_count:
        raise DocumentParsingError(
            "source_page_count_mismatch",
            "The immutable PDF page count differs from its ingestion metadata.",
            409,
        )

    now = datetime.now(UTC)
    pages: list[DocumentPage] = []
    index_objects: dict[str, StoredObject] = {}
    for page_number, source_page in enumerate(reader.pages, start=1):
        try:
            parsed = _extract_page(source_page, page_number)
        except Exception as error:  # Each failed page remains explicit and auditable.
            empty_hash = hashlib.sha256(b"").hexdigest()
            pages.append(
                DocumentPage(
                    source_id=source_id,
                    page_number=page_number,
                    text="",
                    text_sha256=empty_hash,
                    parser_version=PARSER_VERSION,
                    bbox_index_uri=None,
                    bbox_index_sha256=None,
                    parse_status="failed",
                    error={
                        "code": "PARSER_PAGE_EXTRACTION_FAILED",
                        "message": "Page text or locator extraction failed.",
                        "exception_type": type(error).__name__,
                    },
                    created_at=now,
                )
            )
            continue

        try:
            stored = store.put_json(parsed.bbox_index, parsed.bbox_index_sha256)
        except (StorageIntegrityError, OSError) as error:
            raise DocumentParsingError(
                "bbox_index_storage_error",
                "The page coordinate index could not be stored with verified integrity.",
                500,
            ) from error
        if parsed.bbox_index_sha256 not in index_objects:
            existing_index = session.get(StoredObject, parsed.bbox_index_sha256)
            if existing_index is None:
                index_objects[parsed.bbox_index_sha256] = StoredObject(
                    sha256=parsed.bbox_index_sha256,
                    storage_uri=stored.storage_uri,
                    media_type=BBOX_MEDIA_TYPE,
                    byte_size=len(parsed.bbox_index),
                    created_at=now,
                )
            elif (
                existing_index.storage_uri != stored.storage_uri
                or existing_index.media_type != BBOX_MEDIA_TYPE
                or existing_index.byte_size != len(parsed.bbox_index)
            ):
                raise DocumentParsingError(
                    "bbox_index_integrity_error",
                    "Existing coordinate-index metadata failed integrity verification.",
                    500,
                )
        pages.append(
            DocumentPage(
                source_id=source_id,
                page_number=page_number,
                text=parsed.text,
                text_sha256=parsed.text_sha256,
                parser_version=PARSER_VERSION,
                bbox_index_uri=stored.storage_uri,
                bbox_index_sha256=parsed.bbox_index_sha256,
                parse_status="parsed",
                error=None,
                created_at=now,
            )
        )

    failed_count = sum(page.parse_status == "failed" for page in pages)
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="document_parse",
        event_type="document_parsed",
        status="partial_failure" if failed_count else "success",
        payload={
            "source_id": source_id,
            "source_sha256": document.sha256,
            "parser_version": PARSER_VERSION,
            "page_count": len(pages),
            "failed_page_count": failed_count,
        },
        created_at=now,
    )
    session.add_all([*index_objects.values(), *pages, event])
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = _existing_pages(session, source_id)
        if len(concurrent) != document.page_count or any(
            page.parser_version != PARSER_VERSION for page in concurrent
        ):
            raise
        return DocumentParsing(pages=concurrent, idempotent_replay=True)
    return DocumentParsing(pages=pages, idempotent_replay=False)
