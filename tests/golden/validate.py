from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def close(actual: Decimal, expected: Decimal) -> bool:
    return abs(actual - expected) <= Decimal("1e-12") * max(abs(expected), Decimal(1))


def validate_case(entry: dict[str, str]) -> None:
    """Validate one immutable golden case and its expected calculations."""

    source_path = ROOT / entry["source_file"]
    expected_path = ROOT / entry["expected_file"]
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert digest == entry["source_sha256"], (entry["case_id"], "hash")
    case = json.loads(expected_path.read_text(encoding="utf-8"))
    assert case["case_id"] == entry["case_id"]

    facts = {}
    for fact in case["expected_facts"]:
        key = (fact["concept"], fact["period_end"])
        assert key not in facts, (entry["case_id"], "duplicate fact", key)
        facts[key] = Decimal(fact["normalized_value"])

    current = case["report"]["period_end"]
    prior = str(int(current[:4]) - 1) + current[4:]

    def f(concept: str, period: str = current) -> Decimal:
        return facts[(concept, period)]

    calculated = {
        "revenue_growth": (f("revenue") - f("revenue", prior)) / f("revenue", prior),
        "gross_margin": f("gross_profit") / f("revenue"),
        "net_margin": f("net_profit") / f("revenue"),
        "roa": f("net_profit") / ((f("total_assets") + f("total_assets", prior)) / 2),
        "roe": f("net_profit") / ((f("total_equity") + f("total_equity", prior)) / 2),
        "debt_to_assets": f("total_liabilities") / f("total_assets"),
        "current_ratio": f("current_assets") / f("current_liabilities"),
        "quick_ratio": (f("current_assets") - f("inventory")) / f("current_liabilities"),
        "ocf_to_net_profit": f("operating_cash_flow") / f("net_profit"),
        "free_cash_flow": f("operating_cash_flow") - f("capital_expenditure"),
        "accounts_receivable_growth": (f("accounts_receivable") - f("accounts_receivable", prior))
        / f("accounts_receivable", prior),
        "inventory_growth": (f("inventory") - f("inventory", prior)) / f("inventory", prior),
    }
    if f("net_profit", prior) != 0:
        calculated["net_profit_growth"] = (f("net_profit") - f("net_profit", prior)) / f(
            "net_profit", prior
        )
    if f("interest_expense") != 0:
        calculated["interest_coverage"] = f("ebit") / f("interest_expense")
    if f("short_term_debt") != 0:
        calculated["cash_to_short_debt"] = f("cash_and_cash_equivalents") / f("short_term_debt")

    assert f("total_assets") == f("total_liabilities") + f("total_equity"), (
        entry["case_id"],
        "balance sheet",
    )
    assert f("gross_profit") == f("revenue") - f("cost_of_revenue"), (
        entry["case_id"],
        "gross profit",
    )

    expected_metrics = {row["metric_code"]: row for row in case["expected_metrics"]}
    assert len(expected_metrics) == 15, (entry["case_id"], "metric count")
    for code, row in expected_metrics.items():
        if row["status"] == "calculated":
            assert code in calculated, (entry["case_id"], code, "not calculated")
            assert close(calculated[code], Decimal(row["value"])), (
                entry["case_id"],
                code,
                calculated[code],
                row["value"],
            )
        else:
            assert row["value"] is None and row.get("reason"), (
                entry["case_id"],
                code,
                "invalid null",
            )
            assert code not in calculated, (entry["case_id"], code, "unexpected calculation")

    print(f"PASS {entry['case_id']}: facts={len(facts)} metrics={len(expected_metrics)}")


for manifest_entry in manifest["cases"]:
    validate_case(manifest_entry)

print(f"PASS manifest: cases={len(manifest['cases'])}")
