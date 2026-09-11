"""Tests for deterministic, evidence-backed financial visualization specs."""

from datetime import UTC, date, datetime
from decimal import Decimal

from citefin.db.models import (
    AnalysisRun,
    CalculatedMetric,
    Evidence,
    FinancialFact,
    RiskFinding,
)
from citefin.services.visualizations import build_visualization_specs

NOW = datetime(2026, 9, 11, tzinfo=UTC)
PERIOD_END = date(2025, 12, 31)


def _run() -> AnalysisRun:
    return AnalysisRun(
        run_id="run_visualization",
        idempotency_key="visualization-key",
        user_id="visualization-user",
        company_name="可视化测试股份有限公司",
        security_code="600007",
        report_period_end=PERIOD_END,
        as_of=NOW,
        analysis_focus=["comprehensive"],
        status="candidate_complete",
        model_profile="deterministic",
        workflow_version="finance-agent-v1",
        created_at=NOW,
        updated_at=NOW,
    )


def _fact(fact_id: str, concept: str, value: str, page: int) -> FinancialFact:
    return FinancialFact(
        fact_id=fact_id,
        run_id="run_visualization",
        source_id="source_visualization",
        statement_type="income_statement",
        concept=concept,
        label_raw=concept,
        period_start=date(2025, 1, 1),
        period_end=PERIOD_END,
        period_type="duration",
        scope="consolidated",
        currency="CNY",
        display_unit="yuan",
        raw_value=Decimal(value),
        normalized_value=Decimal(value),
        sign_convention="signed_v1",
        page_number=page,
        section="合并报表",
        row_label=concept,
        column_label="2025年度",
        extraction_method="manual",
        confidence=Decimal("1"),
        validation_status="confirmed",
        mapping_version="financial-fact-v1",
        identity_key=fact_id,
        created_at=NOW,
    )


def _metric(metric_id: str, code: str, value: str, unit: str = "ratio") -> CalculatedMetric:
    return CalculatedMetric(
        metric_id=metric_id,
        run_id="run_visualization",
        metric_code=code,
        definition_version="metrics-v1",
        period_end=PERIOD_END,
        input_fact_ids=["fact_profit", "fact_cash"],
        input_snapshot={},
        value=Decimal(value),
        unit=unit,
        status="calculated",
        calculator_version="deterministic-decimal-v1",
        calculated_at=NOW,
    )


def test_builds_three_validated_specs_with_decimal_rows_and_lineage() -> None:
    metrics = [
        _metric("metric_growth", "revenue_growth", "0.2"),
        _metric("metric_margin", "net_margin", "0.1"),
        _metric("metric_coverage", "ocf_to_net_profit", "1.25", "multiple"),
    ]
    evidence = [
        Evidence(
            evidence_id="evidence_growth",
            claim_id="claim_growth",
            evidence_type="metric",
            metric_id="metric_growth",
            supports="supports",
            created_at=NOW,
        ),
        Evidence(
            evidence_id="evidence_cash",
            claim_id="claim_cash",
            evidence_type="metric",
            metric_id="metric_coverage",
            supports="supports",
            created_at=NOW,
        ),
        Evidence(
            evidence_id="evidence_risk",
            claim_id="claim_risk",
            evidence_type="rule",
            rule_id="R_TEST",
            supports="supports",
            created_at=NOW,
        ),
    ]
    risks = [
        RiskFinding(
            risk_id="risk_visualization",
            run_id="run_visualization",
            risk_code="R_TEST",
            period_end=PERIOD_END,
            category="working_capital",
            severity="medium",
            title="测试风险",
            description="只用于契约测试。",
            claim_ids=["claim_risk"],
            status="open",
            limitations=[],
            confidence=Decimal("0.5"),
            created_at=NOW,
        )
    ]

    specs = build_visualization_specs(
        _run(),
        "report_visualization",
        [
            _fact("fact_profit", "net_profit", "120000000", 2),
            _fact("fact_cash", "operating_cash_flow", "150000000", 3),
        ],
        metrics,
        risks,
        evidence,
    )

    assert [spec.chart_key for spec in specs] == [
        "growth_profitability",
        "cash_profit_quality",
        "risk_distribution",
    ]
    assert all(spec.status == "validated" for spec in specs)
    assert all(len(spec.data_snapshot_hash) == 64 for spec in specs)
    growth = specs[0]
    assert growth.dataset["rows"][0]["value"] == "0.2"
    assert growth.encoding["value_format"] == "percent"
    assert growth.evidence_ids == ["evidence_growth"]
    cash = specs[1]
    assert cash.chart_type == "grouped_bar"
    assert cash.encoding["unit"] == "CNY"
    assert cash.dataset["source_refs"][1]["page_number"] == 3
    assert cash.evidence_ids == ["evidence_cash"]
    risk = specs[2]
    assert risk.dataset["rows"] == [
        {"severity": "中", "value": "1", "risk_ids": ["risk_visualization"]}
    ]
    assert risk.evidence_ids == ["evidence_risk"]


def test_omits_charts_that_cannot_be_supported_without_inventing_data() -> None:
    missing_metric = _metric("metric_missing", "revenue_growth", "0.2")
    missing_metric.status = "missing_input"
    missing_metric.value = None
    duplicate_profit = _fact("fact_profit_duplicate", "net_profit", "120000000", 2)

    specs = build_visualization_specs(
        _run(),
        "report_visualization",
        [
            _fact("fact_profit", "net_profit", "120000000", 2),
            duplicate_profit,
            _fact("fact_cash", "operating_cash_flow", "150000000", 3),
        ],
        [missing_metric],
        [],
        [],
    )

    assert specs == []
