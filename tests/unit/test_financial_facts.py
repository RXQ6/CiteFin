"""Unit tests for F005 deterministic mappings and Decimal conversions."""

from decimal import Decimal

import pytest

from citefin.services.financial_facts import (
    FinancialFactError,
    map_financial_concept,
    normalize_value,
)


@pytest.mark.parametrize(
    ("label", "concept"),
    [
        ("营业收入", "revenue"),
        ("应收账款", "accounts_receivable"),
        ("Total assets", "total_assets"),
        ("流动资产合计", "current_assets"),
        ("短期借款", "short_term_debt"),
        ("流动负债合计", "current_liabilities"),
        ("营业成本", "cost_of_revenue"),
        ("毛利润", "gross_profit"),
        ("息税前利润", "ebit"),
        ("利息费用", "interest_expense"),
        ("经营活动产生的现金流量净额", "operating_cash_flow"),
        (
            "购建固定资产、无形资产和其他长期资产支付的现金",
            "capital_expenditure",
        ),
    ],
)
def test_maps_supported_labels_to_versioned_concepts(label: str, concept: str) -> None:
    assert map_financial_concept(label) == concept


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("yuan", Decimal("12.50")),
        ("thousand_yuan", Decimal("12500.00")),
        ("million_yuan", Decimal("12500000.00")),
    ],
)
def test_normalizes_display_units_without_binary_float(unit: str, expected: Decimal) -> None:
    assert normalize_value(Decimal("12.50"), unit) == expected


def test_unknown_label_is_rejected() -> None:
    with pytest.raises(FinancialFactError, match="approved F005 standard concept"):
        map_financial_concept("自定义未知项目")


def test_non_finite_value_is_rejected() -> None:
    with pytest.raises(FinancialFactError, match="finite"):
        normalize_value(Decimal("NaN"), "yuan")
