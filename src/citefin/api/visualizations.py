"""Read-only API for validated, source-backed financial chart specifications."""

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.visualizations import (
    VisualizationAccessError,
    list_owned_visualizations,
)

router = APIRouter(prefix="/analysis-runs", tags=["visualizations"])


class VisualizationResponse(BaseModel):
    visualization_id: str
    run_id: str
    report_id: str
    chart_key: str
    spec_version: str
    chart_type: Literal["bar", "grouped_bar"]
    title: str
    question: str
    dataset: dict[str, Any]
    encoding: dict[str, Any]
    evidence_ids: list[str]
    limitations: list[str]
    data_snapshot_hash: str
    renderer_version: str
    status: Literal["validated", "invalid"]
    created_at: datetime


def _utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.get("/{run_id}/visualizations", response_model=list[VisualizationResponse])
def list_visualizations_endpoint(
    run_id: str,
    user_id: UserIdHeader,
    session: DatabaseSession,
    report_id: Annotated[str | None, Query(min_length=1)] = None,
) -> list[VisualizationResponse]:
    """Return the report chart contracts for an owned analysis run."""

    try:
        specs = list_owned_visualizations(session, run_id, user_id, report_id)
    except VisualizationAccessError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return [
        VisualizationResponse(
            visualization_id=spec.visualization_id,
            run_id=spec.run_id,
            report_id=spec.report_id,
            chart_key=spec.chart_key,
            spec_version=spec.spec_version,
            chart_type=spec.chart_type,
            title=spec.title,
            question=spec.question,
            dataset=spec.dataset,
            encoding=spec.encoding,
            evidence_ids=spec.evidence_ids,
            limitations=spec.limitations,
            data_snapshot_hash=spec.data_snapshot_hash,
            renderer_version=spec.renderer_version,
            status=spec.status,
            created_at=_utc_datetime(spec.created_at),
        )
        for spec in specs
    ]
