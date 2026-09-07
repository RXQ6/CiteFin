"""F013 API for the auditable terminal Goal Gate decision."""

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.goal_gate import (
    GOAL_GATE_VERSION,
    GoalGateError,
    decide_goal_gate,
)

router = APIRouter(prefix="/analysis-runs", tags=["goal-gate"])


class GoalGateRequest(BaseModel):
    """Identify the owned candidate report whose evaluation is gated."""

    report_id: str


class GoalGateResponse(BaseModel):
    """One immutable Goal Gate decision and its terminal evidence."""

    gate_id: str
    run_id: str
    report_id: str
    evaluation_id: str | None
    gate_version: str
    decision: Literal["verified", "revision_required", "blocked", "error"]
    evidence_refs: list[str]
    blocking_reasons: list[dict[str, Any]]
    node_hint: str | None
    repair_instruction: str | None
    created_at: datetime
    idempotent_replay: bool


def _utc_datetime(value: datetime) -> datetime:
    """Normalize SQLite's timezone-naive round-trip to a stable API value."""

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.post(
    "/{run_id}/goal-gate",
    response_model=GoalGateResponse,
    status_code=status.HTTP_201_CREATED,
)
def goal_gate_endpoint(
    run_id: str,
    request: GoalGateRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> GoalGateResponse:
    """Apply the only terminal decision path without issuing investment advice."""

    try:
        result = decide_goal_gate(session, run_id, user_id, request.report_id)
    except GoalGateError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    decision = result.decision
    return GoalGateResponse(
        gate_id=decision.gate_id,
        run_id=decision.run_id,
        report_id=decision.report_id,
        evaluation_id=decision.evaluation_id,
        gate_version=decision.gate_version,
        decision=decision.decision,
        evidence_refs=decision.evidence_refs,
        blocking_reasons=decision.blocking_reasons,
        node_hint=decision.node_hint,
        repair_instruction=decision.repair_instruction,
        created_at=_utc_datetime(decision.created_at),
        idempotent_replay=result.idempotent_replay,
    )


__all__ = ["GOAL_GATE_VERSION", "goal_gate_endpoint"]
