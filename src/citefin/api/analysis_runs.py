"""HTTP contract for creating evidence-driven analysis runs."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Self

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from citefin.api.dependencies import DatabaseSession
from citefin.services.analysis_runs import CreateAnalysisRunCommand, create_analysis_run

router = APIRouter(prefix="/analysis-runs", tags=["analysis-runs"])

CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
SecurityCode = Annotated[
    str,
    StringConstraints(pattern=r"^(?:00[0-3]|30[01]|60[0135]|688)\d{3}$"),
]
UserIdHeader = Annotated[
    str,
    Header(alias="X-User-ID", min_length=1, max_length=128),
]
IdempotencyKeyHeader = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=8, max_length=128),
]


class AnalysisFocus(StrEnum):
    """Supported deterministic analysis slices for the MVP."""

    COMPREHENSIVE = "comprehensive"
    PROFITABILITY = "profitability"
    CASHFLOW = "cashflow"
    SOLVENCY = "solvency"


class CreateAnalysisRunRequest(BaseModel):
    """Validated user intent for one annual-report analysis."""

    company_name: CompanyName
    security_code: SecurityCode
    report_period_end: date
    as_of: datetime = Field(default_factory=lambda: datetime.now(UTC))
    analysis_focus: list[AnalysisFocus] = Field(
        default_factory=lambda: [AnalysisFocus.COMPREHENSIVE], min_length=1
    )

    @field_validator("as_of")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("as_of must include a timezone offset")
        return value.astimezone(UTC)

    @field_validator("analysis_focus")
    @classmethod
    def require_distinct_focus(cls, value: list[AnalysisFocus]) -> list[AnalysisFocus]:
        if len(value) != len(set(value)):
            raise ValueError("analysis_focus cannot contain duplicates")
        if AnalysisFocus.COMPREHENSIVE in value and len(value) > 1:
            raise ValueError("comprehensive cannot be combined with another focus")
        return value

    @model_validator(mode="after")
    def prevent_future_period(self) -> Self:
        if self.report_period_end > self.as_of.date():
            raise ValueError("report_period_end cannot be later than as_of")
        return self


class AnalysisRunResponse(BaseModel):
    """Identifiers and initial state required by clients and operators."""

    run_id: str
    task_id: str
    event_id: str
    checkpoint_id: str
    thread_id: str
    company_name: str
    security_code: str
    report_period_end: date
    as_of: datetime
    analysis_focus: list[str]
    status: str
    current_node: str | None
    workflow_version: str
    created_at: datetime
    idempotent_replay: bool


@router.post("", response_model=AnalysisRunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    request: CreateAnalysisRunRequest,
    response: Response,
    session: DatabaseSession,
    user_id: UserIdHeader,
    idempotency_key: IdempotencyKeyHeader,
) -> AnalysisRunResponse:
    """Create the complete initial persistence bundle or replay the original result."""

    creation = create_analysis_run(
        session,
        CreateAnalysisRunCommand(
            user_id=user_id,
            idempotency_key=idempotency_key,
            company_name=request.company_name,
            security_code=request.security_code,
            report_period_end=request.report_period_end,
            as_of=request.as_of,
            analysis_focus=[focus.value for focus in request.analysis_focus],
        ),
    )
    if creation.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    run = creation.run
    return AnalysisRunResponse(
        run_id=run.run_id,
        task_id=creation.task_id,
        event_id=creation.event_id,
        checkpoint_id=creation.checkpoint_id,
        thread_id=creation.thread_id,
        company_name=run.company_name,
        security_code=run.security_code,
        report_period_end=run.report_period_end,
        as_of=run.as_of,
        analysis_focus=run.analysis_focus,
        status=run.status,
        current_node=run.current_node,
        workflow_version=run.workflow_version,
        created_at=run.created_at,
        idempotent_replay=creation.idempotent_replay,
    )
