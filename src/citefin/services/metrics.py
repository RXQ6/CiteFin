"""Deterministic calculation of the MVP's 15 financial metrics."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import AnalysisRun, AuditEvent, CalculatedMetric, FinancialFact
from citefin.ids import new_prefixed_id

METRIC_DEFINITION_VERSION = "metrics-v1"
CALCULATOR_VERSION = "deterministic-decimal-v1"


@dataclass(frozen=True)
class MetricDefinition:
    """Human-readable, versioned definition used by the calculator."""

    code: str
    name_zh: str
    formula: str
    unit: str
    input_concepts: tuple[str, ...]


@dataclass(frozen=True)
class MetricResult:
    """A calculation result with enough lineage to be independently replayed."""

    definition: MetricDefinition
    period_end: date
    input_fact_ids: tuple[str, ...]
    input_snapshot: dict[str, dict[str, str]]
    value: Decimal | None
    status: str
    reason: str | None


@dataclass(frozen=True)
class MetricCalculation:
    """Persisted results and whether the request was an idempotent replay."""

    metrics: tuple[CalculatedMetric, ...]
    idempotent_replay: bool


class MetricError(Exception):
    """Stable error raised by the metric calculation boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _definition(
    code: str, name_zh: str, formula: str, unit: str, *concepts: str
) -> MetricDefinition:
    return MetricDefinition(code, name_zh, formula, unit, concepts)


METRIC_DEFINITIONS: tuple[MetricDefinition, ...] = (
    _definition(
        "revenue_growth",
        "营业收入增长率",
        "(revenue_t - revenue_t-1) / revenue_t-1",
        "ratio",
        "revenue",
    ),
    _definition(
        "net_profit_growth",
        "净利润增长率",
        "(net_profit_t - net_profit_t-1) / net_profit_t-1",
        "ratio",
        "net_profit",
    ),
    _definition(
        "gross_margin", "毛利率", "gross_profit_t / revenue_t", "ratio", "gross_profit", "revenue"
    ),
    _definition(
        "net_margin", "净利率", "net_profit_t / revenue_t", "ratio", "net_profit", "revenue"
    ),
    _definition(
        "roa",
        "总资产报酬率",
        "net_profit_t / average(total_assets_t, total_assets_t-1)",
        "ratio",
        "net_profit",
        "total_assets",
    ),
    _definition(
        "roe",
        "净资产收益率",
        "net_profit_t / average(total_equity_t, total_equity_t-1)",
        "ratio",
        "net_profit",
        "total_equity",
    ),
    _definition(
        "debt_to_assets",
        "资产负债率",
        "total_liabilities_t / total_assets_t",
        "ratio",
        "total_liabilities",
        "total_assets",
    ),
    _definition(
        "current_ratio",
        "流动比率",
        "current_assets_t / current_liabilities_t",
        "multiple",
        "current_assets",
        "current_liabilities",
    ),
    _definition(
        "quick_ratio",
        "速动比率",
        "(current_assets_t - inventory_t) / current_liabilities_t",
        "multiple",
        "current_assets",
        "inventory",
        "current_liabilities",
    ),
    _definition(
        "ocf_to_net_profit",
        "经营现金流/净利润",
        "operating_cash_flow_t / net_profit_t",
        "multiple",
        "operating_cash_flow",
        "net_profit",
    ),
    _definition(
        "free_cash_flow",
        "自由现金流",
        "operating_cash_flow_t - capital_expenditure_t",
        "CNY",
        "operating_cash_flow",
        "capital_expenditure",
    ),
    _definition(
        "accounts_receivable_growth",
        "应收账款增长率",
        "(accounts_receivable_t - accounts_receivable_t-1) / accounts_receivable_t-1",
        "ratio",
        "accounts_receivable",
    ),
    _definition(
        "inventory_growth",
        "存货增长率",
        "(inventory_t - inventory_t-1) / inventory_t-1",
        "ratio",
        "inventory",
    ),
    _definition(
        "interest_coverage",
        "利息保障倍数",
        "ebit_t / interest_expense_t",
        "multiple",
        "ebit",
        "interest_expense",
    ),
    _definition(
        "cash_to_short_debt",
        "现金短债比",
        "cash_and_cash_equivalents_t / short_term_debt_t",
        "multiple",
        "cash_and_cash_equivalents",
        "short_term_debt",
    ),
)


def _prior_period(period_end: date) -> date:
    try:
        return period_end.replace(year=period_end.year - 1)
    except ValueError:
        return period_end.replace(year=period_end.year - 1, day=28)


def _index_facts(facts: Iterable[FinancialFact]) -> dict[tuple[str, date], list[FinancialFact]]:
    indexed: dict[tuple[str, date], list[FinancialFact]] = {}
    for fact in facts:
        indexed.setdefault((fact.concept, fact.period_end), []).append(fact)
    return indexed


def _snapshot(facts: Iterable[FinancialFact]) -> tuple[tuple[str, ...], dict[str, dict[str, str]]]:
    ordered = sorted(facts, key=lambda fact: (fact.concept, fact.period_end, fact.fact_id))
    return (
        tuple(fact.fact_id for fact in ordered),
        {
            fact.fact_id: {
                "concept": fact.concept,
                "period_end": fact.period_end.isoformat(),
                "normalized_value": str(fact.normalized_value),
            }
            for fact in ordered
        },
    )


def calculate_metrics(facts: Iterable[FinancialFact], period_end: date) -> tuple[MetricResult, ...]:
    """Calculate every metric without floating point or silent missing-data guesses."""

    indexed = _index_facts(facts)
    prior_end = _prior_period(period_end)

    def resolve(concept: str, period: date = period_end) -> tuple[FinancialFact | None, str | None]:
        candidates = indexed.get((concept, period), [])
        if not candidates:
            return None, f"missing_input:{concept}:{period.isoformat()}"
        if len(candidates) != 1 or any(fact.validation_status == "conflict" for fact in candidates):
            return None, f"conflict_input:{concept}:{period.isoformat()}"
        return candidates[0], None

    def result(
        definition: MetricDefinition,
        required: list[tuple[str, date]],
        operation: Callable[[dict[tuple[str, date], Decimal]], Decimal],
    ) -> MetricResult:
        facts_for_metric: list[FinancialFact] = []
        values: dict[tuple[str, date], Decimal] = {}
        problems: list[str] = []
        for concept, period in required:
            fact, problem = resolve(concept, period)
            if fact is not None:
                facts_for_metric.append(fact)
                values[(concept, period)] = fact.normalized_value
            elif problem is not None:
                problems.append(problem)
        input_fact_ids, input_snapshot = _snapshot(facts_for_metric)
        if problems:
            status = (
                "conflict"
                if any(problem.startswith("conflict_input:") for problem in problems)
                else "missing_input"
            )
            return MetricResult(
                definition,
                period_end,
                input_fact_ids,
                input_snapshot,
                None,
                status,
                ";".join(problems),
            )
        try:
            value = operation(values)
        except ZeroDivisionError:
            denominator = next((key for key in required if values.get(key) == 0), required[-1])
            reason = f"zero_denominator:{denominator[0]}:{denominator[1].isoformat()}"
            return MetricResult(
                definition,
                period_end,
                input_fact_ids,
                input_snapshot,
                None,
                "zero_denominator",
                reason,
            )
        return MetricResult(
            definition, period_end, input_fact_ids, input_snapshot, value, "calculated", None
        )

    current = period_end
    previous = prior_end
    revenue_t = ("revenue", current)
    revenue_p = ("revenue", previous)
    profit_t = ("net_profit", current)
    profit_p = ("net_profit", previous)
    assets_t = ("total_assets", current)
    assets_p = ("total_assets", previous)
    equity_t = ("total_equity", current)
    equity_p = ("total_equity", previous)

    def growth(
        values: dict[tuple[str, date], Decimal],
        current_key: tuple[str, date],
        previous_key: tuple[str, date],
    ) -> Decimal:
        return (values[current_key] - values[previous_key]) / values[previous_key]

    def divide(
        values: dict[tuple[str, date], Decimal],
        numerator: tuple[str, date],
        denominator: tuple[str, date],
    ) -> Decimal:
        return values[numerator] / values[denominator]

    specs: tuple[
        tuple[
            MetricDefinition,
            list[tuple[str, date]],
            Callable[[dict[tuple[str, date], Decimal]], Decimal],
        ],
        ...,
    ] = (
        (METRIC_DEFINITIONS[0], [revenue_t, revenue_p], lambda v: growth(v, revenue_t, revenue_p)),
        (METRIC_DEFINITIONS[1], [profit_t, profit_p], lambda v: growth(v, profit_t, profit_p)),
        (
            METRIC_DEFINITIONS[2],
            [("gross_profit", current), revenue_t],
            lambda v: divide(v, ("gross_profit", current), revenue_t),
        ),
        (
            METRIC_DEFINITIONS[3],
            [profit_t, revenue_t],
            lambda v: divide(v, profit_t, revenue_t),
        ),
        (
            METRIC_DEFINITIONS[4],
            [profit_t, assets_t, assets_p],
            lambda v: v[profit_t] / ((v[assets_t] + v[assets_p]) / Decimal(2)),
        ),
        (
            METRIC_DEFINITIONS[5],
            [profit_t, equity_t, equity_p],
            lambda v: v[profit_t] / ((v[equity_t] + v[equity_p]) / Decimal(2)),
        ),
        (
            METRIC_DEFINITIONS[6],
            [("total_liabilities", current), assets_t],
            lambda v: divide(v, ("total_liabilities", current), assets_t),
        ),
        (
            METRIC_DEFINITIONS[7],
            [("current_assets", current), ("current_liabilities", current)],
            lambda v: divide(v, ("current_assets", current), ("current_liabilities", current)),
        ),
        (
            METRIC_DEFINITIONS[8],
            [("current_assets", current), ("inventory", current), ("current_liabilities", current)],
            lambda v: (
                (v[("current_assets", current)] - v[("inventory", current)])
                / v[("current_liabilities", current)]
            ),
        ),
        (
            METRIC_DEFINITIONS[9],
            [("operating_cash_flow", current), profit_t],
            lambda v: divide(v, ("operating_cash_flow", current), profit_t),
        ),
        (
            METRIC_DEFINITIONS[10],
            [("operating_cash_flow", current), ("capital_expenditure", current)],
            lambda v: v[("operating_cash_flow", current)] - v[("capital_expenditure", current)],
        ),
        (
            METRIC_DEFINITIONS[11],
            [("accounts_receivable", current), ("accounts_receivable", previous)],
            lambda v: growth(
                v, ("accounts_receivable", current), ("accounts_receivable", previous)
            ),
        ),
        (
            METRIC_DEFINITIONS[12],
            [("inventory", current), ("inventory", previous)],
            lambda v: growth(v, ("inventory", current), ("inventory", previous)),
        ),
        (
            METRIC_DEFINITIONS[13],
            [("ebit", current), ("interest_expense", current)],
            lambda v: divide(v, ("ebit", current), ("interest_expense", current)),
        ),
        (
            METRIC_DEFINITIONS[14],
            [("cash_and_cash_equivalents", current), ("short_term_debt", current)],
            lambda v: divide(
                v, ("cash_and_cash_equivalents", current), ("short_term_debt", current)
            ),
        ),
    )
    return tuple(
        result(definition, required, operation) for definition, required, operation in specs
    )


def calculate_and_persist_metrics(
    session: Session, run_id: str, user_id: str, period_end: date
) -> MetricCalculation:
    """Calculate and persist one immutable metric set for a user-owned run."""

    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise MetricError("run_not_found", "Analysis run was not found.", 404)
    facts = list(session.scalars(select(FinancialFact).where(FinancialFact.run_id == run_id)))
    if not facts:
        raise MetricError("no_financial_facts", "No normalized financial facts are available.")
    results = calculate_metrics(facts, period_end)
    existing = list(
        session.scalars(select(CalculatedMetric).where(CalculatedMetric.run_id == run_id))
    )
    if existing:
        if len(existing) == len(results) and all(
            metric.metric_code == result.definition.code
            and metric.period_end == result.period_end
            and metric.input_snapshot == result.input_snapshot
            for metric, result in zip(
                sorted(existing, key=lambda row: row.metric_code),
                sorted(results, key=lambda row: row.definition.code),
                strict=True,
            )
        ):
            return MetricCalculation(tuple(sorted(existing, key=lambda row: row.metric_code)), True)
        raise MetricError(
            "metrics_already_calculated", "Metric results already exist for this run."
        )

    now = datetime.now(UTC)
    persisted = [
        CalculatedMetric(
            metric_id=new_prefixed_id("metric"),
            run_id=run_id,
            metric_code=result.definition.code,
            definition_version=METRIC_DEFINITION_VERSION,
            period_end=result.period_end,
            input_fact_ids=list(result.input_fact_ids),
            input_snapshot=result.input_snapshot,
            value=result.value,
            unit=result.definition.unit,
            status=result.status,
            reason=result.reason,
            calculator_version=CALCULATOR_VERSION,
            calculated_at=now,
        )
        for result in results
    ]
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="calculate_metrics",
        event_type="metrics_calculated",
        status="success",
        payload={
            "metric_count": len(persisted),
            "definition_version": METRIC_DEFINITION_VERSION,
            "calculator_version": CALCULATOR_VERSION,
            "statuses": {
                status: sum(metric.status == status for metric in persisted)
                for status in {metric.status for metric in persisted}
            },
        },
        created_at=now,
    )
    session.add_all([*persisted, event])
    session.commit()
    return MetricCalculation(tuple(persisted), False)
