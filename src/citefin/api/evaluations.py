"""F012 API for independent evaluation of persisted report candidates."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.evaluation import (
    EvaluationError,
    evaluate_and_persist_report,
)

router = APIRouter(prefix="/analysis-runs", tags=["evaluations"])


class EvaluateReportRequest(BaseModel):
    """Identify the persisted report candidate to evaluate."""

    report_id: str


class EvaluationResponse(BaseModel):
    """Independent evaluation result and structured repair guidance."""

    evaluation_id: str
    run_id: str
    report_id: str
    evaluator_version: str
    status: Literal["passed", "failed", "error"]
    checks: list[dict[str, Any]]
    blocking_reasons: list[dict[str, Any]]
    input_snapshot: dict[str, Any]
    node_hint: str | None
    repair_instruction: str | None
    created_at: datetime
    idempotent_replay: bool


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.post(
    "/{run_id}/evaluations",
    response_model=EvaluationResponse,
    status_code=status.HTTP_201_CREATED,
)
def evaluate_report_endpoint(
    run_id: str,
    request: EvaluateReportRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> EvaluationResponse:
    """Evaluate a report without changing report, fact, or metric entities."""

    try:
        result = evaluate_and_persist_report(session, run_id, user_id, request.report_id)
    except EvaluationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    evaluation = result.evaluation
    return EvaluationResponse(
        evaluation_id=evaluation.evaluation_id,
        run_id=evaluation.run_id,
        report_id=evaluation.report_id,
        evaluator_version=evaluation.evaluator_version,
        status=evaluation.status,
        checks=evaluation.checks,
        blocking_reasons=evaluation.blocking_reasons,
        input_snapshot=evaluation.input_snapshot,
        node_hint=evaluation.node_hint,
        repair_instruction=evaluation.repair_instruction,
        created_at=_utc_datetime(evaluation.created_at),
        idempotent_replay=result.idempotent_replay,
    )
