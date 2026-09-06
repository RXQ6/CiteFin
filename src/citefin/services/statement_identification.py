"""Deterministic identification of the three consolidated financial statements."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    DocumentPage,
    SourceDocument,
    StatementIdentification,
)
from citefin.ids import new_prefixed_id
from citefin.storage import LocalObjectStore, StorageIntegrityError

STATEMENT_IDENTIFICATION_VERSION = "statement-identification-v1"
STATEMENT_TYPES = ("balance_sheet", "income_statement", "cashflow_statement")

_TITLE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "balance_sheet": (
        re.compile(r"资产负债表"),
        re.compile(r"balance\s+sheet", re.IGNORECASE),
    ),
    "income_statement": (
        re.compile(r"利润表|损益表"),
        re.compile(r"income\s+statement|statement\s+of\s+profit", re.IGNORECASE),
    ),
    "cashflow_statement": (
        re.compile(r"现金流量表"),
        re.compile(r"cash\s+flow(?:s)?\s+statement|statement\s+of\s+cash\s+flows", re.IGNORECASE),
    ),
}
_DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*(?:年|[-/.])\s*"
    r"(?P<month>1[0-2]|0?[1-9])\s*(?:月|[-/.])\s*"
    r"(?P<day>3[01]|[12]\d|0?[1-9])\s*日?"
)
_YEAR_PATTERN = re.compile(r"(?P<year>20\d{2})\s*(?:年|年度)")


class StatementIdentificationError(ValueError):
    """A stable, actionable F004 identification failure."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


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
        raise StatementIdentificationError(
            "source_document_not_found", "Source document was not found.", 404
        )
    return document


def _existing(session: Session, source_id: str) -> list[StatementIdentification]:
    return list(
        session.scalars(
            select(StatementIdentification)
            .where(StatementIdentification.source_id == source_id)
            .order_by(StatementIdentification.statement_type)
        )
    )


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u3000", " ")).strip()


def _scope(context: str) -> str:
    consolidated = bool(re.search(r"合并|consolidated", context, re.IGNORECASE))
    parent = bool(re.search(r"母公司|本公司|parent|separate", context, re.IGNORECASE))
    if consolidated and not parent:
        return "consolidated"
    if parent and not consolidated:
        return "parent"
    return "unknown"


def _period_candidates(text: str) -> list[date]:
    values: list[date] = []
    for match in _DATE_PATTERN.finditer(text):
        try:
            values.append(
                date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            )
        except ValueError:
            continue
    return list(dict.fromkeys(values))


def _period_for_page(text: str, expected: date) -> tuple[date | None, str, bool]:
    dates = _period_candidates(text)
    if expected in dates:
        return expected, "document_and_user_input", False
    if len(dates) == 1:
        return dates[0], "document", dates[0].year != expected.year
    years = {int(match.group("year")) for match in _YEAR_PATTERN.finditer(text)}
    if expected.year in years:
        return expected, "document_year_and_user_input", False
    if not dates and not years:
        return expected, "user_input", False
    if len(dates) > 1:
        return None, "multiple_document_periods", False
    return None, "period_not_confirmed", True


def _title_excerpt(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 24)
    end = min(len(text), match.end() + 72)
    excerpt = text[start:end].strip(" -:：;；,，。()（）[]【】")
    return excerpt[:240]


def _load_locator(
    store: LocalObjectStore, page: DocumentPage
) -> tuple[str | None, list[float] | None, dict[str, Any]]:
    if not page.bbox_index_uri or not page.bbox_index_sha256:
        return None, None, {"locator_type": "page", "page_number": page.page_number}
    try:
        raw = store.read_json(page.bbox_index_sha256, page.bbox_index_uri)
        index = json.loads(raw.decode("utf-8"))
    except (StorageIntegrityError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StatementIdentificationError(
            "locator_integrity_error",
            "The immutable page locator index failed integrity verification.",
            500,
        ) from error
    if index.get("page_number") != page.page_number:
        raise StatementIdentificationError(
            "locator_integrity_error",
            "The page locator index does not match its document page.",
            500,
        )
    regions = index.get("table_regions") or []
    region = regions[0] if regions else {}
    table_id = region.get("table_id")
    bbox = region.get("bbox")
    locator = {
        "locator_type": "table_candidate" if table_id else "page",
        "page_number": page.page_number,
        "table_id": table_id,
        "bbox": bbox,
        "page_text_sha256": page.text_sha256,
        "bbox_index_sha256": page.bbox_index_sha256,
    }
    return table_id, bbox, locator


def _page_candidates(
    store: LocalObjectStore, page: DocumentPage, statement_type: str, expected: date
) -> list[dict[str, Any]]:
    if page.parse_status != "parsed":
        return []
    text = _normalise(page.text)
    table_id, bbox, locator = _load_locator(store, page)
    candidates: list[dict[str, Any]] = []
    for pattern in _TITLE_PATTERNS[statement_type]:
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 80) : min(len(text), match.end() + 120)]
            if re.search(r"目录|目次|contents|table\s+of\s+contents", context, re.IGNORECASE):
                continue
            period_end, period_source, period_conflict = _period_for_page(text, expected)
            candidate = {
                "page_number": page.page_number,
                "title": _title_excerpt(text, match),
                "scope": _scope(context),
                "period_end": period_end.isoformat() if period_end else None,
                "period_source": period_source,
                "period_conflict": period_conflict,
                "table_id": table_id,
                "bbox": bbox,
                "page_text_sha256": page.text_sha256,
                "bbox_index_sha256": page.bbox_index_sha256,
                "locator": locator,
            }
            key = (candidate["page_number"], candidate["scope"], candidate["table_id"])
            if not any(
                (item["page_number"], item["scope"], item["table_id"]) == key for item in candidates
            ):
                candidates.append(candidate)
    return candidates


def _outcome(
    statement_type: str,
    candidates: list[dict[str, Any]],
    expected: date,
) -> dict[str, Any]:
    consolidated = [item for item in candidates if item["scope"] == "consolidated"]
    parent = [item for item in candidates if item["scope"] == "parent"]
    unknown = [item for item in candidates if item["scope"] == "unknown"]
    selected: dict[str, Any] | None = None
    status = "missing"
    reason: dict[str, Any]
    if len(consolidated) == 1:
        selected = consolidated[0]
        if selected["period_conflict"]:
            status = "ambiguous"
            reason = {
                "code": "period_conflict",
                "message": "The statement period conflicts with the requested report period.",
            }
        else:
            status = "located"
            reason = {
                "code": "located",
                "message": "One consolidated statement candidate matched the requested period.",
            }
    elif len(consolidated) > 1:
        status = "ambiguous"
        reason = {
            "code": "multiple_consolidated_candidates",
            "message": "Multiple consolidated statement candidates require user confirmation.",
        }
    elif parent:
        reason = {
            "code": "only_parent_statement_found",
            "message": (
                "Only a parent-company statement was found; it cannot satisfy "
                "the consolidated requirement."
            ),
        }
    elif unknown:
        status = "ambiguous"
        reason = {
            "code": "consolidated_scope_not_explicit",
            "message": "A statement title was found, but its consolidated scope is not explicit.",
        }
        if len(unknown) == 1:
            selected = unknown[0]
    else:
        reason = {
            "code": "statement_title_not_found",
            "message": "No statement title candidate was found in parsed pages.",
        }
    if selected is None and status == "missing" and parent:
        selected = parent[0] if len(parent) == 1 else None
    return {
        "statement_type": statement_type,
        "status": status,
        "title": selected["title"] if selected else None,
        "scope": selected["scope"] if selected else ("parent" if parent else "unknown"),
        "period_end": (
            selected["period_end"] if selected and selected["period_end"] else expected.isoformat()
        )
        if selected
        else None,
        "page_number": selected["page_number"] if selected else None,
        "table_id": selected["table_id"] if selected else None,
        "locator": selected["locator"] if selected else None,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "reason": reason,
    }


def _overall_status(outcomes: list[dict[str, Any]]) -> str:
    statuses = {item["status"] for item in outcomes}
    if statuses == {"located"}:
        return "located"
    if "ambiguous" in statuses:
        return "awaiting_user"
    if statuses == {"missing"}:
        return "missing"
    return "partial"


def identify_statements(
    session: Session,
    store: LocalObjectStore,
    *,
    run_id: str,
    source_id: str,
    user_id: str,
) -> tuple[list[StatementIdentification], bool, str]:
    """Identify required consolidated statements once and preserve all candidates."""

    document = _owned_document(session, run_id, source_id, user_id)
    existing = _existing(session, source_id)
    if existing:
        if len(existing) == len(STATEMENT_TYPES) and all(
            item.algorithm_version == STATEMENT_IDENTIFICATION_VERSION for item in existing
        ):
            return (
                existing,
                True,
                _overall_status(
                    [
                        {
                            "status": item.status,
                        }
                        for item in existing
                    ]
                ),
            )
        raise StatementIdentificationError(
            "statement_state_conflict",
            "Existing statement-identification records are incomplete or use "
            "another algorithm version.",
            409,
        )
    pages = list(
        session.scalars(
            select(DocumentPage)
            .where(DocumentPage.source_id == source_id)
            .order_by(DocumentPage.page_number)
        )
    )
    if not pages:
        raise StatementIdentificationError(
            "document_not_parsed", "Parse the source document before identifying statements.", 409
        )
    if len(pages) != document.page_count:
        raise StatementIdentificationError(
            "parse_incomplete", "All source pages must have a persisted parse outcome.", 409
        )
    run = session.get(AnalysisRun, run_id)
    if run is None:
        raise StatementIdentificationError(
            "analysis_run_not_found", "Analysis run was not found.", 404
        )
    outcomes = [
        _outcome(
            statement_type,
            [
                candidate
                for page in pages
                for candidate in _page_candidates(
                    store, page, statement_type, run.report_period_end
                )
            ],
            run.report_period_end,
        )
        for statement_type in STATEMENT_TYPES
    ]
    now = datetime.now(UTC)
    records = [
        StatementIdentification(
            statement_id=new_prefixed_id("statement"),
            source_id=source_id,
            statement_type=outcome["statement_type"],
            status=outcome["status"],
            title=outcome["title"],
            scope=outcome["scope"],
            period_end=(
                date.fromisoformat(outcome["period_end"]) if outcome["period_end"] else None
            ),
            page_number=outcome["page_number"],
            table_id=outcome["table_id"],
            locator=outcome["locator"],
            candidate_count=outcome["candidate_count"],
            candidates=outcome["candidates"],
            reason=outcome["reason"],
            algorithm_version=STATEMENT_IDENTIFICATION_VERSION,
            created_at=now,
            updated_at=now,
        )
        for outcome in outcomes
    ]
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="statement_extract",
        event_type="statements_identified",
        status=_overall_status(outcomes),
        payload={
            "source_id": source_id,
            "source_sha256": document.sha256,
            "algorithm_version": STATEMENT_IDENTIFICATION_VERSION,
            "statement_statuses": {item["statement_type"]: item["status"] for item in outcomes},
        },
        created_at=now,
    )
    session.add_all([*records, event])
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = _existing(session, source_id)
        if len(concurrent) != len(STATEMENT_TYPES) or any(
            item.algorithm_version != STATEMENT_IDENTIFICATION_VERSION for item in concurrent
        ):
            raise
        return concurrent, True, _overall_status([{"status": item.status} for item in concurrent])
    return records, False, _overall_status(outcomes)
