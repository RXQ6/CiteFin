"""Read-only API for the complete financial-analysis workbench."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.workbench import WorkbenchError, get_workbench_snapshot, list_owned_runs

router = APIRouter(prefix="/analysis-runs", tags=["workbench"])


def _utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class RunSummaryResponse(BaseModel):
    run_id: str
    company_name: str
    security_code: str
    report_period_end: date
    as_of: datetime
    analysis_focus: list[str]
    status: str
    current_node: str | None
    workflow_version: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    failure_code: str | None


class SourceSummaryResponse(BaseModel):
    source_id: str
    file_name: str
    sha256: str
    page_count: int
    language: str
    text_extractable: bool
    parser_version: str
    ingested_at: datetime


class StatementSummaryResponse(BaseModel):
    statement_id: str
    source_id: str
    statement_type: str
    status: str
    title: str | None
    scope: str
    period_end: date | None
    page_number: int | None
    table_id: str | None
    locator: dict[str, Any] | None
    candidate_count: int
    reason: dict[str, Any] | None
    algorithm_version: str


class FactSummaryResponse(BaseModel):
    fact_id: str
    source_id: str
    statement_type: str
    concept: str
    label_raw: str
    period_start: date | None
    period_end: date
    period_type: str
    currency: str
    display_unit: str
    raw_value: Decimal
    normalized_value: Decimal
    page_number: int
    section: str
    row_label: str
    column_label: str
    extraction_method: str
    confidence: Decimal
    validation_status: str
    mapping_version: str
    conflict_group_id: str | None


class MetricSummaryResponse(BaseModel):
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


class ClaimSummaryResponse(BaseModel):
    claim_id: str
    claim_type: str
    text: str
    materiality: str
    status: str
    evidence_ids: list[str]
    created_by: str
    created_at: datetime


class RiskSummaryResponse(BaseModel):
    risk_id: str
    risk_code: str
    period_end: date
    category: str
    severity: str
    title: str
    description: str
    claim_ids: list[str]
    status: str
    limitations: list[str]
    confidence: Decimal
    created_at: datetime


class ReportSummaryResponse(BaseModel):
    report_id: str
    version: int
    status: str
    schema_version: str
    content: dict[str, Any]
    claim_ids: list[str]
    generated_by: str
    created_at: datetime


class EvaluationSummaryResponse(BaseModel):
    evaluation_id: str
    report_id: str
    evaluator_version: str
    status: str
    checks: list[dict[str, Any]]
    blocking_reasons: list[dict[str, Any]]
    input_snapshot: dict[str, Any]
    node_hint: str | None
    repair_instruction: str | None
    created_at: datetime


class GateSummaryResponse(BaseModel):
    gate_id: str
    report_id: str
    evaluation_id: str | None
    gate_version: str
    decision: str
    evidence_refs: list[str]
    blocking_reasons: list[dict[str, Any]]
    node_hint: str | None
    repair_instruction: str | None
    created_at: datetime


class CheckpointSummaryResponse(BaseModel):
    checkpoint_id: str
    thread_id: str
    node: str
    state_version: int
    status: str
    source_ids: list[str]
    fact_ids: list[str]
    metric_ids: list[str]
    claim_ids: list[str]
    report_id: str | None
    created_at: datetime


class WorkbenchResponse(BaseModel):
    run: RunSummaryResponse
    sources: list[SourceSummaryResponse]
    statements: list[StatementSummaryResponse]
    facts: list[FactSummaryResponse]
    metrics: list[MetricSummaryResponse]
    claims: list[ClaimSummaryResponse]
    risks: list[RiskSummaryResponse]
    reports: list[ReportSummaryResponse]
    evaluations: list[EvaluationSummaryResponse]
    gate_decisions: list[GateSummaryResponse]
    checkpoints: list[CheckpointSummaryResponse]


def _run_response(run: Any) -> RunSummaryResponse:
    return RunSummaryResponse(
        run_id=run.run_id,
        company_name=run.company_name,
        security_code=run.security_code,
        report_period_end=run.report_period_end,
        as_of=_utc_datetime(run.as_of),
        analysis_focus=run.analysis_focus,
        status=run.status,
        current_node=run.current_node,
        workflow_version=run.workflow_version,
        created_at=_utc_datetime(run.created_at),
        updated_at=_utc_datetime(run.updated_at),
        completed_at=_utc_datetime(run.completed_at) if run.completed_at else None,
        failure_code=run.failure_code,
    )


@router.get("", response_model=list[RunSummaryResponse])
def list_runs_endpoint(
    user_id: UserIdHeader,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RunSummaryResponse]:
    """List the caller's persisted analysis runs without exposing other users."""

    return [_run_response(run) for run in list_owned_runs(session, user_id, limit=limit)]


@router.get("/{run_id}/workspace", response_model=WorkbenchResponse)
def get_workbench_endpoint(
    run_id: str,
    user_id: UserIdHeader,
    session: DatabaseSession,
) -> WorkbenchResponse:
    """Return one complete, side-effect-free workbench projection."""

    try:
        snapshot = get_workbench_snapshot(session, run_id, user_id)
    except WorkbenchError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error

    return WorkbenchResponse(
        run=_run_response(snapshot.run),
        sources=[SourceSummaryResponse.model_validate(item.__dict__) for item in snapshot.sources],
        statements=[
            StatementSummaryResponse.model_validate(item.__dict__) for item in snapshot.statements
        ],
        facts=[FactSummaryResponse.model_validate(item.__dict__) for item in snapshot.facts],
        metrics=[MetricSummaryResponse.model_validate(item.__dict__) for item in snapshot.metrics],
        claims=[ClaimSummaryResponse.model_validate(item.__dict__) for item in snapshot.claims],
        risks=[RiskSummaryResponse.model_validate(item.__dict__) for item in snapshot.risks],
        reports=[ReportSummaryResponse.model_validate(item.__dict__) for item in snapshot.reports],
        evaluations=[
            EvaluationSummaryResponse.model_validate(item.__dict__) for item in snapshot.evaluations
        ],
        gate_decisions=[
            GateSummaryResponse.model_validate(item.__dict__) for item in snapshot.gate_decisions
        ],
        checkpoints=[
            CheckpointSummaryResponse(
                checkpoint_id=item.checkpoint_id,
                thread_id=item.thread_id,
                node=item.node,
                state_version=item.state_version,
                status=str(item.state_data.get("status", "unknown")),
                source_ids=list(item.state_data.get("source_ids", [])),
                fact_ids=list(item.state_data.get("fact_ids", [])),
                metric_ids=list(item.state_data.get("metric_ids", [])),
                claim_ids=list(item.state_data.get("claim_ids", [])),
                report_id=item.state_data.get("report_id"),
                created_at=_utc_datetime(item.created_at),
            )
            for item in snapshot.checkpoints
        ],
    )
