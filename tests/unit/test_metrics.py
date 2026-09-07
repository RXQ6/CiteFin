"""Tests for F006's deterministic Decimal metric engine."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from citefin.db.models import FinancialFact
from citefin.services.metrics import calculate_metrics

GOLDEN_ROOT = Path(__file__).parents[1] / "golden"


def _facts(case_id: str) -> tuple[list[FinancialFact], dict[str, object]]:
    expected_path = next((GOLDEN_ROOT / "cases").glob(f"{case_id}/expected.json"))
    case = json.loads(expected_path.read_text(encoding="utf-8"))
    facts = [
        FinancialFact(
            fact_id=f"fact_{index}",
            concept=row["concept"],
            period_end=date.fromisoformat(row["period_end"]),
            normalized_value=Decimal(row["normalized_value"]),
            validation_status="extracted",
        )
        for index, row in enumerate(case["expected_facts"])
    ]
    return facts, case


@pytest.mark.parametrize(
    "case_id",
    ["G001_standard_profitable", "G002_profit_cashflow_stress", "G003_unit_and_zero_denominator"],
)
def test_calculates_golden_metrics_with_decimal_lineage(case_id: str) -> None:
    facts, case = _facts(case_id)
    results = calculate_metrics(facts, date.fromisoformat(case["report"]["period_end"]))
    actual = {result.definition.code: result for result in results}

    assert len(results) == 15
    for expected in case["expected_metrics"]:
        result = actual[expected["metric_code"]]
        assert result.status == expected["status"]
        assert result.definition.unit == expected["unit"]
        if expected["value"] is None:
            assert result.value is None
            assert result.reason is not None
        else:
            assert result.value is not None
            assert abs(result.value - Decimal(expected["value"])) <= Decimal("1e-12") * max(
                abs(Decimal(expected["value"])), Decimal(1)
            )
        assert result.input_fact_ids
        assert result.input_snapshot


def test_missing_and_conflicting_inputs_are_structured() -> None:
    facts, _ = _facts("G001_standard_profitable")
    facts = [fact for fact in facts if fact.concept != "revenue" or fact.period_end.year != 2024]
    missing = {
        result.definition.code: result for result in calculate_metrics(facts, date(2025, 12, 31))
    }
    assert missing["revenue_growth"].status == "missing_input"
    assert "missing_input:revenue:2024-12-31" in (missing["revenue_growth"].reason or "")

    conflict = FinancialFact(
        fact_id="fact_conflict",
        concept="revenue",
        period_end=date(2025, 12, 31),
        normalized_value=Decimal("999"),
        validation_status="conflict",
    )
    conflicted = {
        result.definition.code: result
        for result in calculate_metrics([*facts, conflict], date(2025, 12, 31))
    }
    assert conflicted["revenue_growth"].status == "conflict"
