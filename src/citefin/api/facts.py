"""F005 API for deterministic financial-field normalization."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, StringConstraints, model_validator

from citefin.api.analysis_runs import UserIdHeader
from citefin.api.dependencies import DatabaseSession
from citefin.services.financial_facts import (
    DEFAULT_SIGN_CONVENTION,
    FinancialFactError,
    NormalizeFinancialFactCommand,
    normalize_financial_fact,
)

router = APIRouter(prefix="/analysis-runs", tags=["financial-facts"])

StatementType = Literal["balance_sheet", "income_statement", "cashflow_statement"]
PeriodType = Literal["instant", "duration"]
DisplayUnit = Literal["yuan", "thousand_yuan", "million_yuan"]
ExtractionMethod = Literal["table_parser", "text_rule", "manual"]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class NormalizeFinancialFactRequest(BaseModel):
    """One raw statement row with all source and accounting context required by F005."""

    statement_type: StatementType
    raw_label: str = Field(min_length=1, max_length=500)
    raw_value: Decimal
    period_start: date | None = None
    period_end: date
    period_type: PeriodType
    scope: Literal["consolidated"]
    currency: Currency
    display_unit: DisplayUnit
    sign_convention: str = Field(default=DEFAULT_SIGN_CONVENTION, min_length=1, max_length=64)
    page_number: int = Field(ge=1)
    section: str = Field(min_length=1, max_length=200)
    table_id: str | None = Field(default=None, max_length=64)
    row_label: str = Field(min_length=1, max_length=500)
    column_label: str = Field(min_length=1, max_length=500)
    bbox: list[float] | None = None
    extraction_method: ExtractionMethod
    confidence: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))

    @model_validator(mode="after")
    def validate_period_shape(self) -> "NormalizeFinancialFactRequest":
        if self.period_type == "instant" and self.period_start is not None:
            raise ValueError("instant facts must not include period_start")
        if self.period_type == "duration" and self.period_start is None:
            raise ValueError("duration facts must include period_start")
        if self.period_start is not None and self.period_start > self.period_end:
            raise ValueError("period_start cannot be later than period_end")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("bbox must contain four coordinates")
        if not self.raw_value.is_finite():
            raise ValueError("raw_value must be finite")
        if not self.confidence.is_finite():
            raise ValueError("confidence must be finite")
        return self


class FinancialFactResponse(BaseModel):
    """Normalized fact with raw value, source context, and conflict status."""

    fact_id: str
    run_id: str
    source_id: str
    statement_type: str
    concept: str
    label_raw: str
    period_start: date | None
    period_end: date
    period_type: str
    scope: str
    currency: str
    display_unit: str
    raw_value: Decimal
    normalized_value: Decimal
    sign_convention: str
    page_number: int
    section: str
    table_id: str | None
    row_label: str
    column_label: str
    bbox: list[float] | None
    extraction_method: str
    confidence: Decimal
    validation_status: str
    mapping_version: str
    identity_key: str
    conflict_group_id: str | None
    created_at: datetime
    idempotent_replay: bool


@router.post(
    "/{run_id}/documents/{source_id}/facts/normalize",
    response_model=FinancialFactResponse,
    status_code=status.HTTP_201_CREATED,
)
def normalize_fact(
    run_id: str,
    source_id: str,
    request: NormalizeFinancialFactRequest,
    response: Response,
    session: DatabaseSession,
    user_id: UserIdHeader,
) -> FinancialFactResponse:
    """Normalize one F004-linked statement row without overwriting conflicts."""

    try:
        result = normalize_financial_fact(
            session,
            NormalizeFinancialFactCommand(
                run_id=run_id,
                source_id=source_id,
                user_id=user_id,
                statement_type=request.statement_type,
                raw_label=request.raw_label,
                raw_value=request.raw_value,
                period_start=request.period_start,
                period_end=request.period_end,
                period_type=request.period_type,
                scope=request.scope,
                currency=request.currency,
                display_unit=request.display_unit,
                sign_convention=request.sign_convention,
                page_number=request.page_number,
                section=request.section,
                table_id=request.table_id,
                row_label=request.row_label,
                column_label=request.column_label,
                bbox=request.bbox,
                extraction_method=request.extraction_method,
                confidence=request.confidence,
            ),
        )
    except FinancialFactError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    fact = result.fact
    return FinancialFactResponse(
        fact_id=fact.fact_id,
        run_id=fact.run_id,
        source_id=fact.source_id,
        statement_type=fact.statement_type,
        concept=fact.concept,
        label_raw=fact.label_raw,
        period_start=fact.period_start,
        period_end=fact.period_end,
        period_type=fact.period_type,
        scope=fact.scope,
        currency=fact.currency,
        display_unit=fact.display_unit,
        raw_value=fact.raw_value,
        normalized_value=fact.normalized_value,
        sign_convention=fact.sign_convention,
        page_number=fact.page_number,
        section=fact.section,
        table_id=fact.table_id,
        row_label=fact.row_label,
        column_label=fact.column_label,
        bbox=fact.bbox,
        extraction_method=fact.extraction_method,
        confidence=fact.confidence,
        validation_status=fact.validation_status,
        mapping_version=fact.mapping_version,
        identity_key=fact.identity_key,
        conflict_group_id=fact.conflict_group_id,
        created_at=fact.created_at,
        idempotent_replay=result.idempotent_replay,
    )
