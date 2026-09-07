"""Tests for deterministic F010 risk detection."""

from datetime import date
from decimal import Decimal

from citefin.db.models import CalculatedMetric
from citefin.services.metrics import METRIC_DEFINITION_VERSION, METRIC_DEFINITIONS
from citefin.services.risk_detection import build_risk_proposals

PERIOD_END = date(2025, 12, 31)


def _metric(code: str, value: str | None, status: str = "calculated") -> CalculatedMetric:
    definition = next(item for item in METRIC_DEFINITIONS if item.code == code)
    return CalculatedMetric(
        metric_id=f"metric_{code}",
        run_id="run_risk",
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


def test_builds_controlled_risks_with_versioned_rules() -> None:
    values = {definition.code: "1" for definition in METRIC_DEFINITIONS}
    values.update(
        {
            "revenue_growth": "-0.1",
            "accounts_receivable_growth": "0.2",
            "inventory_growth": "0.0",
            "debt_to_assets": "0.8",
            "current_ratio": "0.8",
            "interest_coverage": "1.2",
            "cash_to_short_debt": "0.5",
        }
    )

    proposals = build_risk_proposals([_metric(code, value) for code, value in values.items()])

    assert {proposal.rule.code for proposal in proposals} == {
        "R_REVENUE_DECLINE_V1",
        "R_RECEIVABLES_OUTGROW_REVENUE_V1",
        "R_DEBT_TO_ASSETS_ABOVE_70PCT_V1",
        "R_CURRENT_RATIO_BELOW_ONE_V1",
        "R_INTEREST_COVERAGE_BELOW_1_5_V1",
        "R_CASH_TO_SHORT_DEBT_BELOW_ONE_V1",
    }
    assert all(proposal.rule.code.startswith("R_") for proposal in proposals)
    assert all("买入" not in proposal.rule.description for proposal in proposals)
    assert all("卖出" not in proposal.rule.description for proposal in proposals)


def test_missing_metric_stops_related_judgement_and_lowers_confidence() -> None:
    metrics = [
        _metric(definition.code, None, "zero_denominator")
        if definition.code == "interest_coverage"
        else _metric(definition.code, "1")
        for definition in METRIC_DEFINITIONS
    ]

    proposals = build_risk_proposals(metrics)

    limitation = next(
        proposal for proposal in proposals if proposal.rule.category == "data_quality"
    )
    assert limitation.status == "qualified"
    assert limitation.confidence == Decimal("0.0000")
    assert "interest_coverage" in " ".join(limitation.limitations)
    assert "R_INTEREST_COVERAGE_BELOW_1_5_V1" not in {proposal.rule.code for proposal in proposals}
