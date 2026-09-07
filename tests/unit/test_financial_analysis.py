"""Tests for deterministic F009 claim generation."""

from datetime import date
from decimal import Decimal

import pytest

from citefin.db.models import CalculatedMetric
from citefin.services.financial_analysis import (
    FinancialAnalysisError,
    build_financial_claims,
)
from citefin.services.metrics import METRIC_DEFINITION_VERSION, METRIC_DEFINITIONS

PERIOD_END = date(2025, 12, 31)


def _metric(code: str, value: str | None, status: str = "calculated") -> CalculatedMetric:
    definition = next(item for item in METRIC_DEFINITIONS if item.code == code)
    return CalculatedMetric(
        metric_id=f"metric_{code}",
        run_id="run_analysis",
        metric_code=code,
        definition_version=METRIC_DEFINITION_VERSION,
        period_end=PERIOD_END,
        input_fact_ids=[f"fact_{code}"],
        input_snapshot={},
        value=Decimal(value) if value is not None else None,
        unit=definition.unit,
        status=status,
        reason="zero_denominator:test" if value is None else None,
        calculator_version="test-calculator",
        calculated_at=None,  # type: ignore[arg-type]
    )


def test_builds_calculation_and_rule_backed_inference_claims() -> None:
    values = {definition.code: "1" for definition in METRIC_DEFINITIONS}
    values.update(
        {
            "revenue_growth": "-0.1",
            "net_profit_growth": "-0.2",
            "ocf_to_net_profit": "0.5",
            "free_cash_flow": "-10",
            "accounts_receivable_growth": "0.2",
            "inventory_growth": "0.1",
            "debt_to_assets": "0.8",
            "current_ratio": "0.8",
            "quick_ratio": "0.7",
            "interest_coverage": "1.2",
            "cash_to_short_debt": "0.5",
        }
    )
    proposals = build_financial_claims([_metric(code, value) for code, value in values.items()])

    inference_rules = {
        evidence.rule_id
        for proposal in proposals
        if proposal.claim_type == "inference"
        for evidence in proposal.evidence
        if evidence.evidence_type == "rule"
    }
    assert len([proposal for proposal in proposals if proposal.claim_type == "calculation"]) == 15
    assert len(inference_rules) == 11
    assert all(proposal.evidence for proposal in proposals)
    assert all(
        all(term not in proposal.text for term in ("买入", "卖出", "目标价"))
        for proposal in proposals
    )


def test_unavailable_metric_becomes_explicit_limitation() -> None:
    metrics = [
        _metric(definition.code, None, "zero_denominator")
        if definition.code == "interest_coverage"
        else _metric(definition.code, "1")
        for definition in METRIC_DEFINITIONS
    ]

    proposals = build_financial_claims(metrics)

    limitation = next(proposal for proposal in proposals if proposal.claim_type == "limitation")
    assert "无法计算" in limitation.text
    assert limitation.evidence[0].supports == "qualifies"


def test_incomplete_or_duplicate_metric_set_is_rejected() -> None:
    with pytest.raises(FinancialAnalysisError, match="incomplete"):
        build_financial_claims([_metric("revenue_growth", "1")])
    metrics = [_metric(definition.code, "1") for definition in METRIC_DEFINITIONS]
    with pytest.raises(FinancialAnalysisError, match="Duplicate"):
        build_financial_claims([*metrics, _metric("revenue_growth", "1")])
