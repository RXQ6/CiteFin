"""F007 API for atomic claims and auditable evidence links."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.evidence import EvidenceError, add_evidence, create_claim

router = APIRouter(prefix="/analysis-runs", tags=["evidence"])

ClaimType = Literal["fact", "calculation", "inference", "limitation"]
Materiality = Literal["major", "minor"]
EvidenceType = Literal["source_locator", "fact", "metric", "rule"]
Supports = Literal["supports", "contradicts", "qualifies"]


class CreateClaimRequest(BaseModel):
    """An atomic statement awaiting evidence."""

    claim_type: ClaimType
    text: str = Field(min_length=1, max_length=2000)
    materiality: Materiality
    created_by: str = Field(default="api-v1", min_length=1, max_length=128)


class ClaimResponse(BaseModel):
    """Claim and its current evidence coverage state."""

    claim_id: str
    run_id: str
    claim_type: str
    text: str
    materiality: str
    status: str
    evidence_ids: list[str]
    created_by: str
    created_at: datetime


class AddEvidenceRequest(BaseModel):
    """One evidence link with exactly one primary target."""

    evidence_type: EvidenceType
    supports: Supports
    source_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    locator: dict[str, Any] | None = None
    fact_id: str | None = None
    metric_id: str | None = None
    rule_id: str | None = None
    excerpt: str | None = Field(default=None, max_length=1000)


class EvidenceResponse(BaseModel):
    """Persisted evidence link."""

    evidence_id: str
    claim_id: str
    evidence_type: str
    source_id: str | None
    page_number: int | None
    locator: dict[str, Any] | None
    fact_id: str | None
    metric_id: str | None
    rule_id: str | None
    excerpt: str | None
    supports: str
    created_at: datetime


@router.post(
    "/{run_id}/claims",
    response_model=ClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_claim_endpoint(
    run_id: str,
    request: CreateClaimRequest,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> ClaimResponse:
    """Create a claim without silently inventing evidence."""

    try:
        claim = create_claim(
            session,
            run_id,
            user_id,
            request.claim_type,
            request.text,
            request.materiality,
            request.created_by,
        )
    except EvidenceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return ClaimResponse(
        claim_id=claim.claim_id,
        run_id=claim.run_id,
        claim_type=claim.claim_type,
        text=claim.text,
        materiality=claim.materiality,
        status=claim.status,
        evidence_ids=claim.evidence_ids,
        created_by=claim.created_by,
        created_at=claim.created_at,
    )


@router.post(
    "/{run_id}/claims/{claim_id}/evidence",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_evidence_endpoint(
    run_id: str,
    claim_id: str,
    request: AddEvidenceRequest,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> EvidenceResponse:
    """Attach one source-linked evidence item to a claim."""

    try:
        evidence = add_evidence(
            session,
            run_id,
            user_id,
            claim_id,
            request.evidence_type,
            request.supports,
            request.source_id,
            request.page_number,
            request.locator,
            request.fact_id,
            request.metric_id,
            request.rule_id,
            request.excerpt,
        )
    except EvidenceError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return EvidenceResponse(
        evidence_id=evidence.evidence_id,
        claim_id=evidence.claim_id,
        evidence_type=evidence.evidence_type,
        source_id=evidence.source_id,
        page_number=evidence.page_number,
        locator=evidence.locator,
        fact_id=evidence.fact_id,
        metric_id=evidence.metric_id,
        rule_id=evidence.rule_id,
        excerpt=evidence.excerpt,
        supports=evidence.supports,
        created_at=evidence.created_at,
    )
