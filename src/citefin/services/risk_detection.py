"""Deterministic, evidence-backed F010 risk detection."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    CalculatedMetric,
    Claim,
    Evidence,
    FinancialFact,
    RiskFinding,
)
from citefin.ids import new_prefixed_id
from citefin.services.metrics import METRIC_DEFINITIONS

RISK_DETECTION_VERSION = "risk-detection-v1"

RiskCategory = Literal["profitability", "cashflow", "solvency", "working_capital", "data_quality"]
RiskSeverity = Literal["critical", "high", "medium", "low"]
RiskStatus = Literal["open", "qualified"]


class RiskDetectionError(Exception):
    """Stable error raised at the deterministic risk-detection boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class RiskRule:
    """One versioned predicate and its controlled risk wording."""

    code: str
    category: RiskCategory
    severity: RiskSeverity
    title: str
    description: str
    metric_codes: tuple[str, ...]
    predicate: Callable[[dict[str, Decimal]], bool]


@dataclass(frozen=True)
class RiskProposal:
    """A deterministic risk finding before it is linked to persisted evidence."""

    rule: RiskRule
    status: RiskStatus
    confidence: Decimal
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class RiskDetectionResult:
    """Persisted findings and whether the request replayed an existing result."""

    findings: tuple[RiskFinding, ...]
    idempotent_replay: bool


def _less(code: str, threshold: str) -> Callable[[dict[str, Decimal]], bool]:
    limit = Decimal(threshold)
    return lambda values: values[code] < limit


def _greater(code: str, threshold: str) -> Callable[[dict[str, Decimal]], bool]:
    limit = Decimal(threshold)
    return lambda values: values[code] > limit


def _outgrows(first: str, second: str) -> Callable[[dict[str, Decimal]], bool]:
    return lambda values: values[first] > 0 and values[first] > values[second]


RISK_RULES: tuple[RiskRule, ...] = (
    RiskRule(
        "R_REVENUE_DECLINE_V1",
        "profitability",
        "medium",
        "营业收入下降",
        "营业收入较上期下降，提示收入规模收缩，需要结合行业和业务变化进一步核查。",
        ("revenue_growth",),
        _less("revenue_growth", "0"),
    ),
    RiskRule(
        "R_NET_PROFIT_DECLINE_V1",
        "profitability",
        "medium",
        "净利润下降",
        "净利润较上期下降，提示盈利规模收缩，需要结合利润构成和非经常性损益进一步核查。",
        ("net_profit_growth",),
        _less("net_profit_growth", "0"),
    ),
    RiskRule(
        "R_CASH_CONVERSION_BELOW_ONE_V1",
        "cashflow",
        "medium",
        "利润现金实现不足",
        "经营现金流未覆盖净利润，提示利润的现金实现程度低于1倍。",
        ("ocf_to_net_profit",),
        _less("ocf_to_net_profit", "1"),
    ),
    RiskRule(
        "R_NEGATIVE_FREE_CASH_FLOW_V1",
        "cashflow",
        "medium",
        "自由现金流为负",
        "经营现金流扣除资本性支出后为负，提示现金投入与内部现金生成之间存在压力。",
        ("free_cash_flow",),
        _less("free_cash_flow", "0"),
    ),
    RiskRule(
        "R_RECEIVABLES_OUTGROW_REVENUE_V1",
        "working_capital",
        "medium",
        "应收账款增速高于收入增速",
        "应收账款增速高于营业收入增速，提示营运资金占用变化需要进一步核查。",
        ("accounts_receivable_growth", "revenue_growth"),
        _outgrows("accounts_receivable_growth", "revenue_growth"),
    ),
    RiskRule(
        "R_INVENTORY_OUTGROW_REVENUE_V1",
        "working_capital",
        "medium",
        "存货增速高于收入增速",
        "存货增速高于营业收入增速，提示存货周转和需求变化需要进一步核查。",
        ("inventory_growth", "revenue_growth"),
        _outgrows("inventory_growth", "revenue_growth"),
    ),
    RiskRule(
        "R_DEBT_TO_ASSETS_ABOVE_70PCT_V1",
        "solvency",
        "high",
        "资产负债率较高",
        "资产负债率高于70%，提示资本结构杠杆水平较高。",
        ("debt_to_assets",),
        _greater("debt_to_assets", "0.70"),
    ),
    RiskRule(
        "R_CURRENT_RATIO_BELOW_ONE_V1",
        "solvency",
        "high",
        "流动比率低于1",
        "流动比率低于1，提示流动资产对流动负债的覆盖不足。",
        ("current_ratio",),
        _less("current_ratio", "1"),
    ),
    RiskRule(
        "R_QUICK_RATIO_BELOW_ONE_V1",
        "solvency",
        "medium",
        "速动比率低于1",
        "速动比率低于1，提示扣除存货后的流动资产对流动负债覆盖不足。",
        ("quick_ratio",),
        _less("quick_ratio", "1"),
    ),
    RiskRule(
        "R_INTEREST_COVERAGE_BELOW_1_5_V1",
        "solvency",
        "high",
        "利息保障倍数偏低",
        "利息保障倍数低于1.5倍，提示息税前利润对利息费用的覆盖空间有限。",
        ("interest_coverage",),
        _less("interest_coverage", "1.5"),
    ),
    RiskRule(
        "R_CASH_TO_SHORT_DEBT_BELOW_ONE_V1",
        "solvency",
        "high",
        "现金短债覆盖不足",
        "现金短债比低于1，提示货币资金对短期债务的直接覆盖不足。",
        ("cash_to_short_debt",),
        _less("cash_to_short_debt", "1"),
    ),
)

DATA_INSUFFICIENT_RULE = RiskRule(
    "R_DATA_INSUFFICIENT_V1",
    "data_quality",
    "medium",
    "风险判断数据不足",
    "部分指标缺失、冲突或存在零分母，已停止基于这些指标的风险判断。",
    (),
    lambda _: True,
)


def _metric_map(metrics: Iterable[CalculatedMetric]) -> dict[str, CalculatedMetric]:
    indexed: dict[str, CalculatedMetric] = {}
    for metric in metrics:
        if metric.metric_code in indexed:
            raise RiskDetectionError(
                "duplicate_metric", f"Duplicate calculated metric: {metric.metric_code}."
            )
        indexed[metric.metric_code] = metric
    expected = {definition.code for definition in METRIC_DEFINITIONS}
    if set(indexed) != expected:
        missing = sorted(expected - set(indexed))
        extra = sorted(set(indexed) - set(expected))
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"unexpected={','.join(extra)}")
        raise RiskDetectionError(
            "incomplete_metric_set", "The persisted metric set is incomplete: " + "; ".join(details)
        )
    periods = {metric.period_end for metric in indexed.values()}
    if len(periods) != 1:
        raise RiskDetectionError(
            "metric_period_mismatch", "Calculated metrics use different periods."
        )
    return indexed


def build_risk_proposals(metrics: Iterable[CalculatedMetric]) -> tuple[RiskProposal, ...]:
    """Build controlled risk findings without inventing values for unavailable metrics."""

    indexed = _metric_map(metrics)
    available = {
        code: metric.value
        for code, metric in indexed.items()
        if metric.status == "calculated" and metric.value is not None
    }
    unavailable = sorted(set(indexed) - set(available))
    proposals: list[RiskProposal] = []
    if unavailable:
        proposals.append(
            RiskProposal(
                DATA_INSUFFICIENT_RULE,
                "qualified",
                Decimal("0.0000"),
                tuple(
                    f"指标 {code} 状态为 {indexed[code].status}，未据此生成风险判断。"
                    for code in unavailable
                ),
            )
        )
    values = {code: value for code, value in available.items() if value is not None}
    for rule in RISK_RULES:
        if all(code in values for code in rule.metric_codes) and rule.predicate(values):
            proposals.append(RiskProposal(rule, "open", Decimal("0.8500")))
    return tuple(proposals)


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise RiskDetectionError("run_not_found", "Analysis run was not found.", 404)
    return run


def detect_and_persist_risks(
    session: Session, run_id: str, user_id: str, period_end: date
) -> RiskDetectionResult:
    """Persist one idempotent, evidence-linked deterministic risk result."""

    _owned_run(session, run_id, user_id)
    metrics = list(
        session.scalars(
            select(CalculatedMetric)
            .where(CalculatedMetric.run_id == run_id, CalculatedMetric.period_end == period_end)
            .order_by(CalculatedMetric.metric_code)
        )
    )
    indexed = _metric_map(metrics)
    proposals = build_risk_proposals(metrics)
    existing = list(
        session.scalars(
            select(RiskFinding)
            .where(RiskFinding.run_id == run_id, RiskFinding.period_end == period_end)
            .order_by(RiskFinding.risk_code)
        )
    )
    if existing:
        return RiskDetectionResult(tuple(existing), True)

    facts = {
        fact.fact_id: fact
        for fact in session.scalars(select(FinancialFact).where(FinancialFact.run_id == run_id))
    }
    now = datetime.now(UTC)
    findings: list[RiskFinding] = []
    claims: list[Claim] = []
    evidence_items: list[Evidence] = []
    for proposal in proposals:
        severity = proposal.rule.severity
        limitations = list(proposal.limitations)
        fact_ids: list[str] = []
        if severity in {"critical", "high"}:
            for code in proposal.rule.metric_codes:
                for fact_id in indexed[code].input_fact_ids:
                    if fact_id in facts:
                        fact_ids.append(fact_id)
                        break
            if not fact_ids:
                severity = "medium"
                limitations.append("缺少可验证的原始事实引用，严重程度已降级为medium。")
        claim = Claim(
            claim_id=new_prefixed_id("claim"),
            run_id=run_id,
            claim_type="limitation" if proposal.rule.category == "data_quality" else "inference",
            text=proposal.rule.description,
            materiality="major" if severity in {"critical", "high"} else "minor",
            status="supported",
            evidence_ids=[],
            created_by=RISK_DETECTION_VERSION,
            created_at=now,
        )
        supports: Literal["supports", "qualifies"] = (
            "qualifies" if proposal.rule.category == "data_quality" else "supports"
        )
        for code in proposal.rule.metric_codes:
            evidence = Evidence(
                evidence_id=new_prefixed_id("evidence"),
                claim_id=claim.claim_id,
                evidence_type="metric",
                metric_id=indexed[code].metric_id,
                supports=supports,
                created_at=now,
            )
            claim.evidence_ids = [*claim.evidence_ids, evidence.evidence_id]
            evidence_items.append(evidence)
        rule_evidence = Evidence(
            evidence_id=new_prefixed_id("evidence"),
            claim_id=claim.claim_id,
            evidence_type="rule",
            rule_id=proposal.rule.code,
            supports=supports,
            created_at=now,
        )
        claim.evidence_ids = [*claim.evidence_ids, rule_evidence.evidence_id]
        evidence_items.append(rule_evidence)
        if severity in {"critical", "high"}:
            for fact_id in fact_ids:
                evidence = Evidence(
                    evidence_id=new_prefixed_id("evidence"),
                    claim_id=claim.claim_id,
                    evidence_type="fact",
                    fact_id=fact_id,
                    supports="supports",
                    created_at=now,
                )
                claim.evidence_ids = [*claim.evidence_ids, evidence.evidence_id]
                evidence_items.append(evidence)
        finding = RiskFinding(
            risk_id=new_prefixed_id("risk"),
            run_id=run_id,
            risk_code=proposal.rule.code,
            period_end=period_end,
            category=proposal.rule.category,
            severity=severity,
            title=proposal.rule.title,
            description=proposal.rule.description,
            claim_ids=[claim.claim_id],
            status="qualified" if limitations or proposal.status == "qualified" else "open",
            limitations=limitations,
            confidence=(
                proposal.confidence
                if not limitations
                else min(proposal.confidence, Decimal("0.5000"))
            ),
            created_at=now,
        )
        claims.append(claim)
        findings.append(finding)

    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="detect_risks",
        event_type="risk_detection_completed",
        status="success",
        payload={
            "detection_version": RISK_DETECTION_VERSION,
            "period_end": period_end.isoformat(),
            "risk_count": len(findings),
            "claim_count": len(claims),
            "evidence_count": len(evidence_items),
        },
        created_at=now,
    )
    session.add_all([*findings, *claims, *evidence_items, event])
    session.commit()
    return RiskDetectionResult(tuple(sorted(findings, key=lambda item: item.risk_code)), False)
