"""F011 API for structured, evidence-linked candidate reports."""

from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.report_generation import (
    REPORT_GENERATOR_VERSION,
    REPORT_SCHEMA_VERSION,
    ReportGenerationError,
    generate_and_persist_report,
)

router = APIRouter(prefix="/analysis-runs", tags=["reports"])


class GenerateReportRequest(BaseModel):
    """Target report period for the owned analysis run."""

    period_end: date


class ReportResponse(BaseModel):
    """One versioned candidate report and its structured content."""

    report_id: str
    run_id: str
    version: int
    status: Literal["draft", "candidate", "verified", "superseded"]
    schema_version: str
    content: dict[str, Any]
    claim_ids: list[str]
    generated_by: str
    created_at: datetime
    idempotent_replay: bool


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.post(
    "/{run_id}/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_report_endpoint(
    run_id: str,
    request: GenerateReportRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> ReportResponse:
    """Generate a candidate report from persisted entities without changing them."""

    try:
        result = generate_and_persist_report(session, run_id, user_id, request.period_end)
    except ReportGenerationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    report = result.report
    return ReportResponse(
        report_id=report.report_id,
        run_id=report.run_id,
        version=report.version,
        status=report.status,
        schema_version=report.schema_version,
        content=report.content,
        claim_ids=report.claim_ids,
        generated_by=report.generated_by,
        created_at=_utc_datetime(report.created_at),
        idempotent_replay=result.idempotent_replay,
    )


__all__ = [
    "REPORT_GENERATOR_VERSION",
    "REPORT_SCHEMA_VERSION",
    "generate_report_endpoint",
]
