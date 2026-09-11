"""Deterministic, auditable visualization planning for persisted financial reports."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    CalculatedMetric,
    Evidence,
    FinancialFact,
    RiskFinding,
    VisualizationSpec,
)
from citefin.ids import new_prefixed_id
from citefin.services.metrics import METRIC_DEFINITIONS

VISUALIZATION_SPEC_VERSION = "financial-chart-v1"
VISUALIZATION_RENDERER_VERSION = "echarts-svg-v1"
ALLOWED_CHART_TYPES = frozenset({"bar", "grouped_bar"})

_METRIC_LABELS = {definition.code: definition.name_zh for definition in METRIC_DEFINITIONS}
_RATIO_METRICS = (
    "revenue_growth",
    "net_profit_growth",
    "gross_margin",
    "net_margin",
    "roe",
)
_SEVERITY_ORDER = ("critical", "high", "medium", "low")
_SEVERITY_LABELS = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}


class VisualizationValidationError(ValueError):
    """Raised when a chart draft would misrepresent its persisted source data."""


class VisualizationAccessError(Exception):
    """Stable error raised at the user-owned visualization read boundary."""

    def __init__(self, code: str, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _canonical_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_visualization_payload(
    dataset: dict[str, Any], encoding: dict[str, Any], chart_type: str
) -> None:
    if chart_type not in ALLOWED_CHART_TYPES:
        raise VisualizationValidationError(f"Unsupported chart type: {chart_type}")
    rows = dataset.get("rows")
    source_refs = dataset.get("source_refs")
    if not isinstance(rows, list) or not rows:
        raise VisualizationValidationError("A visualization requires at least one reviewed row.")
    if not isinstance(source_refs, list) or not source_refs:
        raise VisualizationValidationError("A visualization requires persisted source references.")
    x_field = encoding.get("x_field")
    y_field = encoding.get("y_field")
    series_field = encoding.get("series_field")
    if not isinstance(x_field, str) or not isinstance(y_field, str):
        raise VisualizationValidationError("Visualization axes must reference named fields.")
    for row in rows:
        if not isinstance(row, dict) or x_field not in row or y_field not in row:
            raise VisualizationValidationError("Every reviewed row must contain both axis fields.")
        if series_field is not None and series_field not in row:
            raise VisualizationValidationError("Every grouped row must contain the series field.")
        value = row[y_field]
        if value is None:
            raise VisualizationValidationError("Missing observations must not be plotted as zero.")
        try:
            Decimal(str(value))
        except InvalidOperation as error:
            raise VisualizationValidationError(
                "Chart measures must be decimal-compatible."
            ) from error


def _make_spec(
    *,
    run_id: str,
    report_id: str,
    chart_key: str,
    chart_type: str,
    title: str,
    question: str,
    dataset: dict[str, Any],
    encoding: dict[str, Any],
    evidence_ids: list[str],
    limitations: list[str],
    created_at: datetime,
) -> VisualizationSpec:
    validate_visualization_payload(dataset, encoding, chart_type)
    return VisualizationSpec(
        visualization_id=new_prefixed_id("viz"),
        run_id=run_id,
        report_id=report_id,
        chart_key=chart_key,
        spec_version=VISUALIZATION_SPEC_VERSION,
        chart_type=chart_type,
        title=title,
        question=question,
        dataset=dataset,
        encoding=encoding,
        evidence_ids=sorted(set(evidence_ids)),
        limitations=limitations,
        data_snapshot_hash=_canonical_hash(dataset),
        renderer_version=VISUALIZATION_RENDERER_VERSION,
        status="validated",
        created_at=created_at,
    )


def _evidence_indexes(
    evidence: Iterable[Evidence],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    by_metric: dict[str, list[str]] = defaultdict(list)
    by_claim: dict[str, list[str]] = defaultdict(list)
    for item in evidence:
        by_claim[item.claim_id].append(item.evidence_id)
        if item.metric_id:
            by_metric[item.metric_id].append(item.evidence_id)
    return by_metric, by_claim


def _growth_profitability_spec(
    run: AnalysisRun,
    report_id: str,
    metrics: list[CalculatedMetric],
    evidence_by_metric: dict[str, list[str]],
    created_at: datetime,
) -> VisualizationSpec | None:
    selected = [
        metric
        for metric in metrics
        if metric.metric_code in _RATIO_METRICS
        and metric.status == "calculated"
        and metric.value is not None
        and metric.unit == "ratio"
    ]
    if not selected:
        return None
    selected.sort(key=lambda metric: _RATIO_METRICS.index(metric.metric_code))
    rows = [
        {
            "label": _METRIC_LABELS[metric.metric_code],
            "value": str(metric.value),
            "metric_id": metric.metric_id,
            "period_end": metric.period_end.isoformat(),
        }
        for metric in selected
    ]
    plotted = {metric.metric_code for metric in selected}
    omitted = [_METRIC_LABELS[code] for code in _RATIO_METRICS if code not in plotted]
    limitations = [f"未绘制不可用指标：{'、'.join(omitted)}。"] if omitted else []
    evidence_ids = [
        evidence_id
        for metric in selected
        for evidence_id in evidence_by_metric.get(metric.metric_id, [])
    ]
    return _make_spec(
        run_id=run.run_id,
        report_id=report_id,
        chart_key="growth_profitability",
        chart_type="bar",
        title="增长与盈利指标",
        question="本报告期的增长与盈利指标处于什么水平？",
        dataset={
            "dimensions": ["label", "period_end"],
            "measures": ["value"],
            "rows": rows,
            "source_refs": [
                {"entity_type": "metric", "entity_id": metric.metric_id} for metric in selected
            ],
        },
        encoding={
            "x_field": "label",
            "y_field": "value",
            "series_field": None,
            "unit": "ratio",
            "value_format": "percent",
            "display_scale": "1",
        },
        evidence_ids=evidence_ids,
        limitations=limitations,
        created_at=created_at,
    )


def _unique_current_fact(
    facts: list[FinancialFact], concept: str, period_end: date
) -> FinancialFact | None:
    candidates = [
        fact
        for fact in facts
        if fact.concept == concept
        and fact.period_end == period_end
        and fact.normalized_value is not None
        and fact.scope == "consolidated"
    ]
    return candidates[0] if len(candidates) == 1 else None


def _cash_profit_spec(
    run: AnalysisRun,
    report_id: str,
    facts: list[FinancialFact],
    evidence_by_metric: dict[str, list[str]],
    metrics: list[CalculatedMetric],
    created_at: datetime,
) -> VisualizationSpec | None:
    profit = _unique_current_fact(facts, "net_profit", run.report_period_end)
    cash = _unique_current_fact(facts, "operating_cash_flow", run.report_period_end)
    if profit is None or cash is None or profit.currency != cash.currency:
        return None
    coverage = next(
        (
            metric
            for metric in metrics
            if metric.metric_code == "ocf_to_net_profit"
            and metric.status == "calculated"
            and metric.value is not None
        ),
        None,
    )
    evidence_ids = evidence_by_metric.get(coverage.metric_id, []) if coverage else []
    rows = [
        {
            "period_end": run.report_period_end.isoformat(),
            "measure": label,
            "value": str(fact.normalized_value),
            "fact_id": fact.fact_id,
        }
        for label, fact in (("净利润", profit), ("经营现金流", cash))
    ]
    limitations = []
    if coverage is None:
        limitations.append("经营现金流覆盖倍数不可用，图中仅比较已确认金额。")
    return _make_spec(
        run_id=run.run_id,
        report_id=report_id,
        chart_key="cash_profit_quality",
        chart_type="grouped_bar",
        title="净利润与经营现金流对比",
        question="经营现金流是否覆盖净利润？",
        dataset={
            "dimensions": ["period_end", "measure"],
            "measures": ["value"],
            "rows": rows,
            "source_refs": [
                {
                    "entity_type": "fact",
                    "entity_id": fact.fact_id,
                    "source_id": fact.source_id,
                    "page_number": fact.page_number,
                }
                for fact in (profit, cash)
            ],
        },
        encoding={
            "x_field": "period_end",
            "y_field": "value",
            "series_field": "measure",
            "unit": profit.currency,
            "value_format": "currency_100m",
            "display_scale": "100000000",
        },
        evidence_ids=evidence_ids,
        limitations=limitations,
        created_at=created_at,
    )


def _risk_distribution_spec(
    run: AnalysisRun,
    report_id: str,
    risk_findings: list[RiskFinding],
    evidence_by_claim: dict[str, list[str]],
    created_at: datetime,
) -> VisualizationSpec | None:
    selected = [risk for risk in risk_findings if risk.period_end == run.report_period_end]
    if not selected:
        return None
    counts = Counter(risk.severity for risk in selected)
    rows = [
        {
            "severity": _SEVERITY_LABELS[severity],
            "value": str(counts[severity]),
            "risk_ids": sorted(risk.risk_id for risk in selected if risk.severity == severity),
        }
        for severity in _SEVERITY_ORDER
        if counts[severity]
    ]
    evidence_ids = [
        evidence_id
        for risk in selected
        for claim_id in risk.claim_ids
        for evidence_id in evidence_by_claim.get(claim_id, [])
    ]
    return _make_spec(
        run_id=run.run_id,
        report_id=report_id,
        chart_key="risk_distribution",
        chart_type="bar",
        title="风险发现分布",
        question="当前证据支持的风险发现按严重程度如何分布？",
        dataset={
            "dimensions": ["severity"],
            "measures": ["value"],
            "rows": rows,
            "source_refs": [
                {"entity_type": "risk", "entity_id": risk.risk_id} for risk in selected
            ],
        },
        encoding={
            "x_field": "severity",
            "y_field": "value",
            "series_field": None,
            "unit": "count",
            "value_format": "integer",
            "display_scale": "1",
        },
        evidence_ids=evidence_ids,
        limitations=["风险数量反映规则命中，不代表发生概率或投资评级。"],
        created_at=created_at,
    )


def build_visualization_specs(
    run: AnalysisRun,
    report_id: str,
    facts: Iterable[FinancialFact],
    metrics: Iterable[CalculatedMetric],
    risk_findings: Iterable[RiskFinding],
    evidence: Iterable[Evidence],
) -> list[VisualizationSpec]:
    """Build the allowlisted chart set without inventing observations or code."""

    fact_list = list(facts)
    metric_list = list(metrics)
    risk_list = list(risk_findings)
    evidence_by_metric, evidence_by_claim = _evidence_indexes(evidence)
    created_at = datetime.now(UTC)
    drafts = (
        _growth_profitability_spec(run, report_id, metric_list, evidence_by_metric, created_at),
        _cash_profit_spec(run, report_id, fact_list, evidence_by_metric, metric_list, created_at),
        _risk_distribution_spec(run, report_id, risk_list, evidence_by_claim, created_at),
    )
    return [draft for draft in drafts if draft is not None]


def list_owned_visualizations(
    session: Session, run_id: str, user_id: str, report_id: str | None = None
) -> list[VisualizationSpec]:
    """Return validated specs for one owned run without exposing other users' data."""

    owned = session.scalar(
        select(AnalysisRun.run_id).where(
            AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id
        )
    )
    if owned is None:
        raise VisualizationAccessError("run_not_found", "Analysis run was not found.")
    query = select(VisualizationSpec).where(VisualizationSpec.run_id == run_id)
    if report_id is not None:
        query = query.where(VisualizationSpec.report_id == report_id)
    return list(
        session.scalars(query.order_by(VisualizationSpec.created_at, VisualizationSpec.chart_key))
    )
