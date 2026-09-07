"""F017 API for report-to-PDF evidence navigation."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.evidence_viewer import EvidenceViewerError, get_report_evidence_view

router = APIRouter(prefix="/analysis-runs", tags=["evidence-viewer"])
LocatorStatus = Literal["available", "unavailable", "not_applicable"]


class SourcePageViewResponse(BaseModel):
    """One resolved or explicitly unavailable PDF page locator."""

    source_id: str
    file_name: str | None
    page_number: int
    locator: dict[str, Any] | None
    excerpt: str | None
    content_url: str | None
    status: LocatorStatus
    unavailable_reason: str | None


class EvidenceItemViewResponse(BaseModel):
    """Evidence identity, relation, target, and page projections."""

    evidence_id: str
    evidence_type: str
    supports: str
    target_id: str | None
    excerpt: str | None
    source_pages: list[SourcePageViewResponse]
    locator_status: LocatorStatus
    unavailable_reason: str | None


class ClaimEvidenceViewResponse(BaseModel):
    """One report claim and its complete evidence-navigation state."""

    claim_id: str
    claim_type: str
    text: str
    materiality: str
    status: str
    evidence: list[EvidenceItemViewResponse]
    missing_evidence_ids: list[str]
    locator_status: LocatorStatus
    unavailable_reason: str | None


class ReportEvidenceViewResponse(BaseModel):
    """Read-only page evidence view for one owned report."""

    report_id: str
    report_status: str
    schema_version: str
    version: int
    claims: list[ClaimEvidenceViewResponse]
    missing_claim_ids: list[str]


@router.get("/{run_id}/evidence-view", response_model=ReportEvidenceViewResponse)
def get_evidence_view_endpoint(
    run_id: str,
    user_id: UserIdHeader,
    session: DatabaseSession,
    report_id: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> ReportEvidenceViewResponse:
    """Return the latest or requested report with explicit page-evidence links."""

    try:
        view = get_report_evidence_view(session, run_id, user_id, report_id)
    except EvidenceViewerError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return ReportEvidenceViewResponse(
        report_id=view.report_id,
        report_status=view.report_status,
        schema_version=view.schema_version,
        version=view.version,
        claims=[
            ClaimEvidenceViewResponse(
                claim_id=claim.claim_id,
                claim_type=claim.claim_type,
                text=claim.text,
                materiality=claim.materiality,
                status=claim.status,
                evidence=[
                    EvidenceItemViewResponse(
                        evidence_id=item.evidence_id,
                        evidence_type=item.evidence_type,
                        supports=item.supports,
                        target_id=item.target_id,
                        excerpt=item.excerpt,
                        source_pages=[
                            SourcePageViewResponse(**source_page.__dict__)
                            for source_page in item.source_pages
                        ],
                        locator_status=item.locator_status,
                        unavailable_reason=item.unavailable_reason,
                    )
                    for item in claim.evidence
                ],
                missing_evidence_ids=claim.missing_evidence_ids,
                locator_status=claim.locator_status,
                unavailable_reason=claim.unavailable_reason,
            )
            for claim in view.claims
        ],
        missing_claim_ids=view.missing_claim_ids,
    )
