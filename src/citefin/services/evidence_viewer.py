"""Read-only F017 report-to-source evidence projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    CalculatedMetric,
    Claim,
    DocumentPage,
    Evidence,
    FinancialFact,
    Report,
    SourceDocument,
)

LocatorStatus = Literal["available", "unavailable", "not_applicable"]


class EvidenceViewerError(Exception):
    """Stable failure raised by the read-only evidence viewer boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class SourcePageView:
    """One bounded page locator suitable for a browser PDF viewer."""

    source_id: str
    file_name: str | None
    page_number: int
    locator: dict[str, Any] | None
    excerpt: str | None
    content_url: str | None
    status: LocatorStatus
    unavailable_reason: str | None


@dataclass(frozen=True)
class EvidenceItemView:
    """One evidence item and all page-level source projections it resolves to."""

    evidence_id: str
    evidence_type: str
    supports: str
    target_id: str | None
    excerpt: str | None
    source_pages: list[SourcePageView]
    locator_status: LocatorStatus
    unavailable_reason: str | None


@dataclass(frozen=True)
class ClaimEvidenceView:
    """One report claim with explicit evidence coverage and locator status."""

    claim_id: str
    claim_type: str
    text: str
    materiality: str
    status: str
    evidence: list[EvidenceItemView]
    missing_evidence_ids: list[str]
    locator_status: LocatorStatus
    unavailable_reason: str | None


@dataclass(frozen=True)
class ReportEvidenceView:
    """Latest or requested report projected onto its persisted evidence graph."""

    report_id: str
    report_status: str
    schema_version: str
    version: int
    claims: list[ClaimEvidenceView]
    missing_claim_ids: list[str]


def _owned_report(session: Session, run_id: str, user_id: str, report_id: str | None) -> Report:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise EvidenceViewerError("run_not_found", "Analysis run was not found.", 404)
    query = select(Report).where(Report.run_id == run_id)
    if report_id is not None:
        query = query.where(Report.report_id == report_id)
    else:
        query = query.order_by(Report.version.desc())
    report = session.scalar(query)
    if report is None:
        raise EvidenceViewerError(
            "report_not_found", "No report is available for this analysis run.", 404
        )
    return report


def _page_excerpt(text: str, maximum: int = 500) -> str | None:
    normalized = " ".join(text.split())
    if not normalized:
        return None
    return normalized if len(normalized) <= maximum else f"{normalized[:maximum].rstrip()}…"


def _fact_locator(fact: FinancialFact) -> dict[str, Any]:
    return {
        "section": fact.section,
        "table_id": fact.table_id,
        "row_label": fact.row_label,
        "column_label": fact.column_label,
        "bbox": fact.bbox,
    }


def _target_id(evidence: Evidence) -> str | None:
    for value in (evidence.source_id, evidence.fact_id, evidence.metric_id, evidence.rule_id):
        if value is not None:
            return value
    return None


def _source_references(
    evidence: Evidence,
    facts: dict[str, FinancialFact],
    metrics: dict[str, CalculatedMetric],
) -> list[tuple[str, int, dict[str, Any] | None]]:
    if evidence.evidence_type == "source_locator":
        if evidence.source_id is None or evidence.page_number is None:
            return []
        return [(evidence.source_id, evidence.page_number, evidence.locator)]
    if evidence.evidence_type == "fact":
        fact = facts.get(evidence.fact_id or "")
        return [(fact.source_id, fact.page_number, _fact_locator(fact))] if fact else []
    if evidence.evidence_type == "metric":
        metric = metrics.get(evidence.metric_id or "")
        if metric is None:
            return []
        references: list[tuple[str, int, dict[str, Any] | None]] = []
        for fact_id in metric.input_fact_ids:
            fact = facts.get(fact_id)
            if fact is not None:
                references.append((fact.source_id, fact.page_number, _fact_locator(fact)))
        return references
    return []


def _page_view(
    session: Session,
    run_id: str,
    evidence_excerpt: str | None,
    source_id: str,
    page_number: int,
    locator: dict[str, Any] | None,
    sources: dict[str, SourceDocument],
) -> SourcePageView:
    source = sources.get(source_id)
    if source is None:
        return SourcePageView(
            source_id=source_id,
            file_name=None,
            page_number=page_number,
            locator=locator,
            excerpt=evidence_excerpt,
            content_url=None,
            status="unavailable",
            unavailable_reason="source_document_not_found",
        )
    if page_number < 1 or page_number > source.page_count:
        return SourcePageView(
            source_id=source_id,
            file_name=source.file_name,
            page_number=page_number,
            locator=locator,
            excerpt=evidence_excerpt,
            content_url=None,
            status="unavailable",
            unavailable_reason="page_out_of_range",
        )
    page = session.get(DocumentPage, (source_id, page_number))
    if page is None or page.parse_status != "parsed":
        return SourcePageView(
            source_id=source_id,
            file_name=source.file_name,
            page_number=page_number,
            locator=locator,
            excerpt=evidence_excerpt,
            content_url=None,
            status="unavailable",
            unavailable_reason="page_not_parsed",
        )
    return SourcePageView(
        source_id=source_id,
        file_name=source.file_name,
        page_number=page_number,
        locator=locator,
        excerpt=evidence_excerpt or _page_excerpt(page.text),
        content_url=f"/api/v1/analysis-runs/{run_id}/documents/{source_id}/content",
        status="available",
        unavailable_reason=None,
    )


def _evidence_view(
    session: Session,
    run_id: str,
    evidence: Evidence,
    facts: dict[str, FinancialFact],
    metrics: dict[str, CalculatedMetric],
    sources: dict[str, SourceDocument],
) -> EvidenceItemView:
    references = _source_references(evidence, facts, metrics)
    source_pages = [
        _page_view(
            session,
            run_id,
            evidence.excerpt,
            source_id,
            page_number,
            locator,
            sources,
        )
        for source_id, page_number, locator in references
    ]
    if any(page.status == "available" for page in source_pages):
        locator_status: LocatorStatus = "available"
        unavailable_reason = None
    elif source_pages:
        locator_status = "unavailable"
        unavailable_reason = "source_page_unavailable"
    elif evidence.evidence_type == "rule":
        locator_status = "not_applicable"
        unavailable_reason = "rule_has_no_source_page"
    else:
        locator_status = "unavailable"
        unavailable_reason = "evidence_target_unresolved"
    return EvidenceItemView(
        evidence_id=evidence.evidence_id,
        evidence_type=evidence.evidence_type,
        supports=evidence.supports,
        target_id=_target_id(evidence),
        excerpt=evidence.excerpt,
        source_pages=source_pages,
        locator_status=locator_status,
        unavailable_reason=unavailable_reason,
    )


def get_report_evidence_view(
    session: Session,
    run_id: str,
    user_id: str,
    report_id: str | None = None,
) -> ReportEvidenceView:
    """Return an owned report with bounded page evidence and explicit gaps."""

    report = _owned_report(session, run_id, user_id, report_id)
    claims = list(
        session.scalars(
            select(Claim).where(Claim.run_id == run_id, Claim.claim_id.in_(report.claim_ids))
            if report.claim_ids
            else select(Claim).where(false())
        )
    )
    claim_map = {claim.claim_id: claim for claim in claims}
    evidence_ids = [evidence_id for claim in claims for evidence_id in claim.evidence_ids]
    evidence = list(
        session.scalars(
            select(Evidence).where(Evidence.evidence_id.in_(evidence_ids))
            if evidence_ids
            else select(Evidence).where(false())
        )
    )
    evidence_map = {item.evidence_id: item for item in evidence}
    facts = {
        fact.fact_id: fact
        for fact in session.scalars(select(FinancialFact).where(FinancialFact.run_id == run_id))
    }
    metrics = {
        metric.metric_id: metric
        for metric in session.scalars(
            select(CalculatedMetric).where(CalculatedMetric.run_id == run_id)
        )
    }
    sources = {
        source.source_id: source
        for source in session.scalars(select(SourceDocument).where(SourceDocument.run_id == run_id))
    }

    claim_views = []
    for claim_id in report.claim_ids:
        claim = claim_map.get(claim_id)
        if claim is None:
            continue
        missing_evidence_ids = [
            evidence_id for evidence_id in claim.evidence_ids if evidence_id not in evidence_map
        ]
        evidence_views = [
            _evidence_view(session, run_id, evidence_map[evidence_id], facts, metrics, sources)
            for evidence_id in claim.evidence_ids
            if evidence_id in evidence_map
        ]
        if any(item.locator_status == "available" for item in evidence_views):
            locator_status: LocatorStatus = "available"
            unavailable_reason = None
        elif not claim.evidence_ids:
            locator_status = "unavailable"
            unavailable_reason = "claim_has_no_evidence"
        elif missing_evidence_ids:
            locator_status = "unavailable"
            unavailable_reason = "claim_evidence_missing"
        else:
            locator_status = "unavailable"
            unavailable_reason = "claim_has_no_page_evidence"
        claim_views.append(
            ClaimEvidenceView(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                text=claim.text,
                materiality=claim.materiality,
                status=claim.status,
                evidence=evidence_views,
                missing_evidence_ids=missing_evidence_ids,
                locator_status=locator_status,
                unavailable_reason=unavailable_reason,
            )
        )
    return ReportEvidenceView(
        report_id=report.report_id,
        report_status=report.status,
        schema_version=report.schema_version,
        version=report.version,
        claims=claim_views,
        missing_claim_ids=[claim_id for claim_id in report.claim_ids if claim_id not in claim_map],
    )
