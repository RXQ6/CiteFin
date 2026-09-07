"""F010 API for deterministic, evidence-linked risk findings."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.risk_detection import (
    RISK_DETECTION_VERSION,
    RiskDetectionError,
    detect_and_persist_risks,
)

router = APIRouter(prefix="/analysis-runs", tags=["risk-detection"])


class DetectRisksRequest(BaseModel):
    """Target period for the persisted metric set being evaluated."""

    period_end: date


class RiskFindingResponse(BaseModel):
    """One persisted risk finding with its claim and evidence references."""

    risk_id: str
    run_id: str
    risk_code: str
    period_end: date
    category: Literal["profitability", "cashflow", "solvency", "working_capital", "data_quality"]
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    description: str
    claim_ids: list[str]
    status: Literal["open", "qualified", "dismissed"]
    limitations: list[str]
    confidence: Decimal
    created_at: datetime


class DetectRisksResponse(BaseModel):
    """The deterministic, replayable F010 finding set."""

    run_id: str
    period_end: date
    detection_version: str
    idempotent_replay: bool
    findings: list[RiskFindingResponse]


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.post(
    "/{run_id}/risk-detection",
    response_model=DetectRisksResponse,
    status_code=status.HTTP_201_CREATED,
)
def detect_risks_endpoint(
    run_id: str,
    request: DetectRisksRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> DetectRisksResponse:
    """Create auditable deterministic risk findings without investment instructions."""

    try:
        result = detect_and_persist_risks(session, run_id, user_id, request.period_end)
    except RiskDetectionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return DetectRisksResponse(
        run_id=run_id,
        period_end=request.period_end,
        detection_version=RISK_DETECTION_VERSION,
        idempotent_replay=result.idempotent_replay,
        findings=[
            RiskFindingResponse(
                risk_id=finding.risk_id,
                run_id=finding.run_id,
                risk_code=finding.risk_code,
                period_end=finding.period_end,
                category=finding.category,
                severity=finding.severity,
                title=finding.title,
                description=finding.description,
                claim_ids=finding.claim_ids,
                status=finding.status,
                limitations=finding.limitations,
                confidence=finding.confidence,
                created_at=_utc_datetime(finding.created_at),
            )
            for finding in result.findings
        ],
    )
