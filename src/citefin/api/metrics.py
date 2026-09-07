"""F006 API for deterministic, source-linked financial metrics."""

from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.metrics import MetricError, calculate_and_persist_metrics

router = APIRouter(prefix="/analysis-runs", tags=["metrics"])


class CalculateMetricsRequest(BaseModel):
    """The target report period for one deterministic metric set."""

    period_end: date


class CalculatedMetricResponse(BaseModel):
    """A persisted metric with formula and fact lineage."""

    metric_id: str
    metric_code: str
    definition_version: str
    period_end: date
    input_fact_ids: list[str]
    input_snapshot: dict[str, dict[str, str]]
    value: Decimal | None
    unit: str
    status: str
    reason: str | None
    calculator_version: str
    calculated_at: datetime


class CalculateMetricsResponse(BaseModel):
    """The complete versioned result set for one report period."""

    run_id: str
    period_end: date
    idempotent_replay: bool
    metrics: list[CalculatedMetricResponse]


@router.post(
    "/{run_id}/metrics/calculate",
    response_model=CalculateMetricsResponse,
    status_code=status.HTTP_201_CREATED,
)
def calculate_metrics_endpoint(
    run_id: str,
    request: CalculateMetricsRequest,
    response: Response,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> CalculateMetricsResponse:
    """Calculate all 15 metrics using only persisted normalized facts."""

    try:
        calculation = calculate_and_persist_metrics(session, run_id, user_id, request.period_end)
    except MetricError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if calculation.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return CalculateMetricsResponse(
        run_id=run_id,
        period_end=request.period_end,
        idempotent_replay=calculation.idempotent_replay,
        metrics=[
            CalculatedMetricResponse(
                metric_id=metric.metric_id,
                metric_code=metric.metric_code,
                definition_version=metric.definition_version,
                period_end=metric.period_end,
                input_fact_ids=metric.input_fact_ids,
                input_snapshot=metric.input_snapshot,
                value=metric.value,
                unit=metric.unit,
                status=metric.status,
                reason=metric.reason,
                calculator_version=metric.calculator_version,
                calculated_at=metric.calculated_at,
            )
            for metric in calculation.metrics
        ],
    )
