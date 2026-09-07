"""F009 API for deterministic, evidence-linked financial analysis claims."""

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.financial_analysis import (
    ANALYSIS_VERSION,
    FinancialAnalysisError,
    analyze_and_persist_claims,
)

router = APIRouter(prefix="/analysis-runs", tags=["financial-analysis"])


class AnalyzeFinancialsRequest(BaseModel):
    """Target period for the persisted metric set being interpreted."""

    period_end: date


class AnalysisClaimResponse(BaseModel):
    """One generated atomic claim and its evidence IDs."""

    claim_id: str
    run_id: str
    claim_type: Literal["calculation", "inference", "limitation"]
    text: str
    materiality: Literal["major", "minor"]
    status: str
    evidence_ids: list[str]
    created_by: str
    created_at: datetime


class AnalyzeFinancialsResponse(BaseModel):
    """The deterministic, replayable F009 claim set."""

    run_id: str
    period_end: date
    analysis_version: str
    idempotent_replay: bool
    claims: list[AnalysisClaimResponse]


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.post(
    "/{run_id}/financial-analysis",
    response_model=AnalyzeFinancialsResponse,
    status_code=status.HTTP_201_CREATED,
)
def analyze_financials_endpoint(
    run_id: str,
    request: AnalyzeFinancialsRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> AnalyzeFinancialsResponse:
    """Create auditable calculation and inference claims without free-form facts."""

    try:
        result = analyze_and_persist_claims(session, run_id, user_id, request.period_end)
    except FinancialAnalysisError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return AnalyzeFinancialsResponse(
        run_id=run_id,
        period_end=request.period_end,
        analysis_version=ANALYSIS_VERSION,
        idempotent_replay=result.idempotent_replay,
        claims=[
            AnalysisClaimResponse(
                claim_id=claim.claim_id,
                run_id=claim.run_id,
                claim_type=claim.claim_type,
                text=claim.text,
                materiality=claim.materiality,
                status=claim.status,
                evidence_ids=claim.evidence_ids,
                created_by=claim.created_by,
                created_at=_utc_datetime(claim.created_at),
            )
            for claim in result.claims
        ],
    )
