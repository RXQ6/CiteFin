"""Deterministic F009 financial analysis claims with metric evidence."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import AnalysisRun, AuditEvent, CalculatedMetric, Claim, Evidence
from citefin.ids import new_prefixed_id
from citefin.services.metrics import METRIC_DEFINITIONS

ANALYSIS_VERSION = "financial-analysis-v1"

ClaimType = Literal["calculation", "inference", "limitation"]
EvidenceType = Literal["metric", "rule"]


class FinancialAnalysisError(Exception):
    """Stable error raised at the deterministic financial-analysis boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class EvidenceSpec:
    """One validated primary evidence target for a generated claim."""

    evidence_type: EvidenceType
    metric_id: str | None = None
    rule_id: str | None = None
    supports: Literal["supports", "qualifies"] = "supports"


@dataclass(frozen=True)
class ClaimProposal:
    """A deterministic atomic claim before persistence."""

    claim_type: ClaimType
    text: str
    materiality: Literal["major", "minor"]
    evidence: tuple[EvidenceSpec, ...]


@dataclass(frozen=True)
class FinancialAnalysisResult:
    """Persisted claims and whether the request replayed an existing result."""

    claims: tuple[Claim, ...]
    idempotent_replay: bool


def _decimal_text(value: Decimal) -> str:
    """Render a Decimal without binary-float conversion or redundant zeros."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _display_value(metric: CalculatedMetric) -> str:
    if metric.value is None:
        raise ValueError("calculated metrics must have a value")
    if metric.unit == "ratio":
        return f"{_decimal_text(metric.value * Decimal(100))}%"
    if metric.unit == "multiple":
        return f"{_decimal_text(metric.value)}倍"
    return f"{_decimal_text(metric.value)}元"


def _metric_map(metrics: Iterable[CalculatedMetric]) -> dict[str, CalculatedMetric]:
    indexed: dict[str, CalculatedMetric] = {}
    for metric in metrics:
        if metric.metric_code in indexed:
            raise FinancialAnalysisError(
                "duplicate_metric", f"Duplicate calculated metric: {metric.metric_code}."
            )
        indexed[metric.metric_code] = metric
    expected = {definition.code for definition in METRIC_DEFINITIONS}
    if set(indexed) != expected:
        missing = sorted(expected - set(indexed))
        extra = sorted(set(indexed) - expected)
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"unexpected={','.join(extra)}")
        raise FinancialAnalysisError(
            "incomplete_metric_set", "The persisted metric set is incomplete: " + "; ".join(details)
        )
    return indexed


def _calculated_value(metric: CalculatedMetric | None) -> Decimal | None:
    if metric is None or metric.status != "calculated" or metric.value is None:
        return None
    return metric.value


def build_financial_claims(metrics: Iterable[CalculatedMetric]) -> tuple[ClaimProposal, ...]:
    """Build reproducible calculation, limitation, and inference claims."""

    indexed = _metric_map(metrics)
    definitions = {definition.code: definition for definition in METRIC_DEFINITIONS}
    period_end = next(iter(indexed.values())).period_end
    proposals: list[ClaimProposal] = []

    for code in sorted(indexed):
        metric = indexed[code]
        definition = definitions[code]
        evidence = (EvidenceSpec("metric", metric_id=metric.metric_id),)
        if metric.status == "calculated" and metric.value is not None:
            proposals.append(
                ClaimProposal(
                    claim_type="calculation",
                    text=(
                        f"截至{period_end.isoformat()}，{definition.name_zh}为"
                        f"{_display_value(metric)}；公式为{definition.formula}。"
                    ),
                    materiality="major",
                    evidence=evidence,
                )
            )
        else:
            reason = metric.reason or "未提供可计算结果"
            proposals.append(
                ClaimProposal(
                    claim_type="limitation",
                    text=(
                        f"截至{period_end.isoformat()}，{definition.name_zh}无法计算；"
                        f"状态为{metric.status}，原因是{reason}，不以0或无穷值替代。"
                    ),
                    materiality="minor",
                    evidence=(
                        EvidenceSpec("metric", metric_id=metric.metric_id, supports="qualifies"),
                    ),
                )
            )

    def value(code: str) -> Decimal | None:
        return _calculated_value(indexed.get(code))

    def inference(
        rule_id: str,
        text: str,
        metric_codes: tuple[str, ...],
    ) -> None:
        evidence = tuple(
            [EvidenceSpec("metric", metric_id=indexed[code].metric_id) for code in metric_codes]
            + [EvidenceSpec("rule", rule_id=rule_id)]
        )
        proposals.append(
            ClaimProposal(
                claim_type="inference",
                text=text,
                materiality="major",
                evidence=evidence,
            )
        )

    revenue_growth = value("revenue_growth")
    if revenue_growth is not None and revenue_growth < 0:
        inference(
            "A_REVENUE_DECLINE_V1",
            "营业收入较上期下降，提示收入规模收缩；该观察不等同于对未来经营结果的预测。",
            ("revenue_growth",),
        )

    net_profit_growth = value("net_profit_growth")
    if net_profit_growth is not None and net_profit_growth < 0:
        inference(
            "A_NET_PROFIT_DECLINE_V1",
            "净利润较上期下降，提示盈利规模收缩；该观察不等同于对未来收益的判断。",
            ("net_profit_growth",),
        )

    ocf_to_net_profit = value("ocf_to_net_profit")
    if ocf_to_net_profit is not None and ocf_to_net_profit < 1:
        inference(
            "A_CASH_CONVERSION_BELOW_ONE_V1",
            "经营现金流未覆盖净利润，提示利润的现金实现程度低于1倍；该观察不替代对现金流原因的核查。",
            ("ocf_to_net_profit",),
        )

    free_cash_flow = value("free_cash_flow")
    if free_cash_flow is not None and free_cash_flow < 0:
        inference(
            "A_NEGATIVE_FREE_CASH_FLOW_V1",
            "自由现金流为负，表示经营现金流扣除资本性支出后为负；该观察不构成交易建议。",
            ("free_cash_flow",),
        )

    accounts_receivable_growth = value("accounts_receivable_growth")
    if (
        accounts_receivable_growth is not None
        and revenue_growth is not None
        and accounts_receivable_growth > 0
        and accounts_receivable_growth > revenue_growth
    ):
        inference(
            "A_RECEIVABLES_OUTGROW_REVENUE_V1",
            "应收账款增速高于营业收入增速，提示营运资金占用变化需要进一步核查。",
            ("accounts_receivable_growth", "revenue_growth"),
        )

    inventory_growth = value("inventory_growth")
    if (
        inventory_growth is not None
        and revenue_growth is not None
        and inventory_growth > 0
        and inventory_growth > revenue_growth
    ):
        inference(
            "A_INVENTORY_OUTGROW_REVENUE_V1",
            "存货增速高于营业收入增速，提示存货周转和需求变化需要进一步核查。",
            ("inventory_growth", "revenue_growth"),
        )

    debt_to_assets = value("debt_to_assets")
    if debt_to_assets is not None and debt_to_assets > Decimal("0.70"):
        inference(
            "A_DEBT_TO_ASSETS_ABOVE_70PCT_V1",
            "资产负债率高于70%，提示资本结构杠杆水平较高。",
            ("debt_to_assets",),
        )

    current_ratio = value("current_ratio")
    if current_ratio is not None and current_ratio < 1:
        inference(
            "A_CURRENT_RATIO_BELOW_ONE_V1",
            "流动比率低于1，提示流动资产对流动负债的覆盖不足。",
            ("current_ratio",),
        )

    quick_ratio = value("quick_ratio")
    if quick_ratio is not None and quick_ratio < 1:
        inference(
            "A_QUICK_RATIO_BELOW_ONE_V1",
            "速动比率低于1，提示扣除存货后的流动资产对流动负债覆盖不足。",
            ("quick_ratio",),
        )

    interest_coverage = value("interest_coverage")
    if interest_coverage is not None and interest_coverage < Decimal("1.5"):
        inference(
            "A_INTEREST_COVERAGE_BELOW_1_5_V1",
            "利息保障倍数低于1.5倍，提示息税前利润对利息费用的覆盖空间有限。",
            ("interest_coverage",),
        )

    cash_to_short_debt = value("cash_to_short_debt")
    if cash_to_short_debt is not None and cash_to_short_debt < 1:
        inference(
            "A_CASH_TO_SHORT_DEBT_BELOW_ONE_V1",
            "现金短债比低于1，提示货币资金对短期债务的直接覆盖不足。",
            ("cash_to_short_debt",),
        )

    return tuple(proposals)


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise FinancialAnalysisError("run_not_found", "Analysis run was not found.", 404)
    return run


def analyze_and_persist_claims(
    session: Session, run_id: str, user_id: str, period_end: date
) -> FinancialAnalysisResult:
    """Persist one idempotent, source-linked deterministic analysis result."""

    _owned_run(session, run_id, user_id)
    metrics = list(
        session.scalars(
            select(CalculatedMetric)
            .where(
                CalculatedMetric.run_id == run_id,
                CalculatedMetric.period_end == period_end,
            )
            .order_by(CalculatedMetric.metric_code)
        )
    )
    proposals = build_financial_claims(metrics)
    existing = list(
        session.scalars(
            select(Claim)
            .where(Claim.run_id == run_id, Claim.created_by == ANALYSIS_VERSION)
            .order_by(Claim.claim_id)
        )
    )
    if existing:
        return FinancialAnalysisResult(tuple(existing), True)

    now = datetime.now(UTC)
    claims: list[Claim] = []
    evidence_items: list[Evidence] = []
    for proposal in proposals:
        claim = Claim(
            claim_id=new_prefixed_id("claim"),
            run_id=run_id,
            claim_type=proposal.claim_type,
            text=proposal.text,
            materiality=proposal.materiality,
            status="supported",
            evidence_ids=[],
            created_by=ANALYSIS_VERSION,
            created_at=now,
        )
        for spec in proposal.evidence:
            evidence = Evidence(
                evidence_id=new_prefixed_id("evidence"),
                claim_id=claim.claim_id,
                evidence_type=spec.evidence_type,
                metric_id=spec.metric_id,
                rule_id=spec.rule_id,
                supports=spec.supports,
                created_at=now,
            )
            claim.evidence_ids = [*claim.evidence_ids, evidence.evidence_id]
            evidence_items.append(evidence)
        claims.append(claim)

    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="analyze_financials",
        event_type="financial_analysis_completed",
        status="success",
        payload={
            "analysis_version": ANALYSIS_VERSION,
            "period_end": period_end.isoformat(),
            "claim_count": len(claims),
            "evidence_count": len(evidence_items),
        },
        created_at=now,
    )
    session.add_all([*claims, *evidence_items, event])
    session.commit()
    return FinancialAnalysisResult(tuple(sorted(claims, key=lambda claim: claim.claim_id)), False)
