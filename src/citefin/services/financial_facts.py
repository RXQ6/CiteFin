"""Deterministic F005 field mapping and decimal normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    FinancialFact,
    SourceDocument,
    StatementIdentification,
)
from citefin.ids import new_prefixed_id

FINANCIAL_FACT_MAPPING_VERSION = "financial-fact-mapping-v1"
DEFAULT_SIGN_CONVENTION = "as_reported_v1"
DISPLAY_UNIT_MULTIPLIERS: dict[str, Decimal] = {
    "yuan": Decimal("1"),
    "thousand_yuan": Decimal("1000"),
    "million_yuan": Decimal("1000000"),
}

_LABEL_RULES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        "cash_and_cash_equivalents",
        (re.compile(r"货币资金|现金及现金等价物|cash\s+and\s+cash\s+equivalents", re.I),),
    ),
    (
        "accounts_receivable",
        (re.compile(r"应收账款|accounts?\s+receivable", re.I),),
    ),
    ("inventory", (re.compile(r"存货|inventor(?:y|ies)", re.I),)),
    ("total_assets", (re.compile(r"资产总计|total\s+assets", re.I),)),
    ("total_liabilities", (re.compile(r"负债合计|total\s+liabilities", re.I),)),
    (
        "total_equity",
        (re.compile(r"所有者权益合计|股东权益合计|total\s+equity", re.I),),
    ),
    (
        "revenue",
        (re.compile(r"营业收入|主营业务收入|operating\s+revenue|revenue", re.I),),
    ),
    (
        "operating_cost",
        (re.compile(r"营业成本|主营业务成本|operating\s+cost|cost\s+of\s+revenue", re.I),),
    ),
    ("operating_profit", (re.compile(r"营业利润|operating\s+profit", re.I),)),
    ("total_profit", (re.compile(r"利润总额|total\s+profit", re.I),)),
    ("net_profit", (re.compile(r"净利润|net\s+(?:profit|income)", re.I),)),
    (
        "net_cash_from_operating_activities",
        (
            re.compile(
                r"经营活动产生的现金流量净额|net\s+cash(?:\s+flows?)?\s+from\s+operating",
                re.I,
            ),
        ),
    ),
    (
        "net_cash_from_investing_activities",
        (
            re.compile(
                r"投资活动产生的现金流量净额|net\s+cash(?:\s+flows?)?\s+from\s+investing",
                re.I,
            ),
        ),
    ),
    (
        "net_cash_from_financing_activities",
        (
            re.compile(
                r"筹资活动产生的现金流量净额|net\s+cash(?:\s+flows?)?\s+from\s+financing",
                re.I,
            ),
        ),
    ),
    (
        "net_change_in_cash",
        (
            re.compile(
                r"现金及现金等价物净增加额|net\s+(?:increase|change)\s+in\s+cash",
                re.I,
            ),
        ),
    ),
)


class FinancialFactError(ValueError):
    """Stable, actionable F005 normalization failure."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class NormalizeFinancialFactCommand:
    """Validated source row values accepted by the F005 normalizer."""

    run_id: str
    source_id: str
    user_id: str
    statement_type: str
    raw_label: str
    raw_value: Decimal
    period_start: date | None
    period_end: date
    period_type: str
    scope: str
    currency: str
    display_unit: str
    sign_convention: str
    page_number: int
    section: str
    table_id: str | None
    row_label: str
    column_label: str
    bbox: list[float] | None
    extraction_method: str
    confidence: Decimal


@dataclass(frozen=True)
class FinancialFactNormalization:
    """Persisted F005 fact and whether the request replayed an existing row."""

    fact: FinancialFact
    idempotent_replay: bool


def map_financial_concept(raw_label: str) -> str:
    """Map a report row label to one versioned, deterministic concept."""

    label = re.sub(r"\s+", " ", raw_label.replace("\u3000", " ")).strip()
    matches = [
        concept
        for concept, patterns in _LABEL_RULES
        if any(pattern.search(label) for pattern in patterns)
    ]
    if not matches:
        raise FinancialFactError(
            "unmapped_label",
            "The report row label has no approved F005 standard concept mapping.",
        )
    if len(matches) > 1:
        raise FinancialFactError(
            "ambiguous_label",
            "The report row label matches multiple F005 standard concepts.",
        )
    return matches[0]


def normalize_value(raw_value: Decimal, display_unit: str) -> Decimal:
    """Convert a disclosed decimal amount to yuan without binary floating point."""

    multiplier = DISPLAY_UNIT_MULTIPLIERS.get(display_unit)
    if multiplier is None:
        raise FinancialFactError("invalid_display_unit", "The display unit is not supported.")
    if not raw_value.is_finite():
        raise FinancialFactError("invalid_numeric_value", "The raw value must be finite.")
    return raw_value * multiplier


def _owned_source(session: Session, command: NormalizeFinancialFactCommand) -> SourceDocument:
    source = session.scalar(
        select(SourceDocument)
        .join(AnalysisRun)
        .where(
            SourceDocument.source_id == command.source_id,
            SourceDocument.run_id == command.run_id,
            AnalysisRun.user_id == command.user_id,
        )
    )
    if source is None:
        raise FinancialFactError("source_document_not_found", "Source document was not found.", 404)
    return source


def _require_statement_ready(session: Session, command: NormalizeFinancialFactCommand) -> None:
    statement = session.scalar(
        select(StatementIdentification).where(
            StatementIdentification.source_id == command.source_id,
            StatementIdentification.statement_type == command.statement_type,
        )
    )
    if statement is None:
        raise FinancialFactError(
            "statement_not_identified",
            "Run F004 statement identification before normalizing financial facts.",
            409,
        )
    if statement.status != "located" or statement.scope != "consolidated":
        raise FinancialFactError(
            "statement_not_ready",
            "Only a located consolidated F004 statement can provide F005 facts.",
            409,
        )


def _identity_key(command: NormalizeFinancialFactCommand, concept: str) -> str:
    return "|".join(
        (
            command.source_id,
            concept,
            command.period_end.isoformat(),
            command.period_type,
            command.scope,
            command.currency,
        )
    )


def _same_fact(
    existing: FinancialFact,
    command: NormalizeFinancialFactCommand,
    concept: str,
    normalized_value: Decimal,
) -> bool:
    return (
        existing.concept == concept
        and existing.raw_value == command.raw_value
        and existing.normalized_value == normalized_value
        and existing.period_start == command.period_start
        and existing.period_end == command.period_end
        and existing.period_type == command.period_type
        and existing.currency == command.currency
        and existing.display_unit == command.display_unit
        and existing.page_number == command.page_number
        and existing.row_label == command.row_label
        and existing.column_label == command.column_label
    )


def normalize_financial_fact(
    session: Session, command: NormalizeFinancialFactCommand
) -> FinancialFactNormalization:
    """Validate F004 context, map a row, preserve conflicts, and persist one fact."""

    source = _owned_source(session, command)
    if command.scope != "consolidated":
        raise FinancialFactError(
            "unsupported_scope",
            "F005 MVP only accepts explicitly consolidated facts.",
        )
    if command.period_type == "instant" and command.period_start is not None:
        raise FinancialFactError(
            "invalid_period_shape",
            "Instant facts must not include period_start.",
        )
    if command.period_type == "duration" and command.period_start is None:
        raise FinancialFactError(
            "invalid_period_shape",
            "Duration facts must include period_start.",
        )
    if command.period_start is not None and command.period_start > command.period_end:
        raise FinancialFactError(
            "invalid_period_range",
            "period_start cannot be later than period_end.",
        )
    if len(command.currency) != 3 or not command.currency.isupper():
        raise FinancialFactError("invalid_currency", "currency must be an uppercase ISO code.")
    if not command.confidence.is_finite() or not Decimal("0") <= command.confidence <= Decimal("1"):
        raise FinancialFactError("invalid_confidence", "confidence must be between 0 and 1.")

    _require_statement_ready(session, command)
    concept = map_financial_concept(command.raw_label)
    normalized_value = normalize_value(command.raw_value, command.display_unit)
    identity_key = _identity_key(command, concept)
    existing = list(
        session.scalars(
            select(FinancialFact)
            .where(FinancialFact.identity_key == identity_key)
            .order_by(FinancialFact.created_at)
        )
    )
    for fact in existing:
        if _same_fact(fact, command, concept, normalized_value):
            return FinancialFactNormalization(fact=fact, idempotent_replay=True)

    conflict_group_id = existing[0].conflict_group_id if existing else None
    if existing and conflict_group_id is None:
        conflict_group_id = new_prefixed_id("conflict")
        for fact in existing:
            fact.validation_status = "conflict"
            fact.conflict_group_id = conflict_group_id

    now = datetime.now(UTC)
    fact = FinancialFact(
        fact_id=new_prefixed_id("fact"),
        run_id=command.run_id,
        source_id=source.source_id,
        statement_type=command.statement_type,
        concept=concept,
        label_raw=command.raw_label,
        period_start=command.period_start,
        period_end=command.period_end,
        period_type=command.period_type,
        scope=command.scope,
        currency=command.currency,
        display_unit=command.display_unit,
        raw_value=command.raw_value,
        normalized_value=normalized_value,
        sign_convention=command.sign_convention,
        page_number=command.page_number,
        section=command.section,
        table_id=command.table_id,
        row_label=command.row_label,
        column_label=command.column_label,
        bbox=command.bbox,
        extraction_method=command.extraction_method,
        confidence=command.confidence,
        validation_status="conflict" if existing else "extracted",
        mapping_version=FINANCIAL_FACT_MAPPING_VERSION,
        identity_key=identity_key,
        conflict_group_id=conflict_group_id,
        created_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=command.run_id,
        trace_id=new_prefixed_id("trace"),
        node="field_normalization",
        event_type="financial_fact_normalized",
        status="conflict" if existing else "success",
        payload={
            "source_id": command.source_id,
            "fact_id": fact.fact_id,
            "concept": concept,
            "identity_key": identity_key,
            "mapping_version": FINANCIAL_FACT_MAPPING_VERSION,
            "validation_status": fact.validation_status,
            "conflict_group_id": conflict_group_id,
        },
        created_at=now,
    )
    session.add_all([fact, event])
    session.commit()
    return FinancialFactNormalization(fact=fact, idempotent_replay=False)
