"""Tests for deterministic F011 report assembly."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from citefin.db.models import (
    AnalysisRun,
    CalculatedMetric,
    Claim,
    Evidence,
    FinancialFact,
    RiskFinding,
    SourceDocument,
)
from citefin.services.report_generation import (
    REPORT_SCHEMA_VERSION,
    ReportGenerationError,
    build_report_content,
)

NOW = datetime(2026, 9, 7, tzinfo=UTC)
PERIOD_END = date(2025, 12, 31)


def _inputs() -> tuple[
    AnalysisRun,
    list[FinancialFact],
    list[CalculatedMetric],
    list[Claim],
    list[Evidence],
    list[RiskFinding],
    list[SourceDocument],
]:
    run = AnalysisRun(
        run_id="run_report",
        idempotency_key="report-key",
        user_id="report-user",
        company_name="报告示例股份有限公司",
        security_code="600005",
        report_period_end=PERIOD_END,
        as_of=NOW,
        analysis_focus=["comprehensive"],
        status="running",
        current_node="write_report",
        model_profile="deterministic-test",
        workflow_version="1.1.0",
        created_at=NOW,
        updated_at=NOW,
    )
    source = SourceDocument(
        source_id="src_report",
        run_id=run.run_id,
        document_type="annual_report",
        file_name="report.pdf",
        media_type="application/pdf",
        sha256="e" * 64,
        storage_uri="object://" + "e" * 64,
        language="zh-CN",
        page_count=1,
        text_extractable=True,
        parser_version="test",
        ingested_at=NOW,
    )
    fact = FinancialFact(
        fact_id="fact_report_revenue",
        run_id=run.run_id,
        source_id=source.source_id,
        statement_type="income_statement",
        concept="revenue",
        label_raw="营业收入",
        period_end=PERIOD_END,
        period_type="duration",
        scope="consolidated",
        currency="CNY",
        display_unit="million_yuan",
        raw_value=Decimal("100"),
        normalized_value=Decimal("100000000"),
        sign_convention="signed_v1",
        page_number=12,
        section="合并利润表",
        row_label="营业收入",
        column_label="2025年",
        extraction_method="manual",
        confidence=Decimal("1"),
        validation_status="extracted",
        mapping_version="financial-fact-v1",
        identity_key="report-revenue",
        created_at=NOW,
    )
    metric = CalculatedMetric(
        metric_id="metric_report_revenue_growth",
        run_id=run.run_id,
        metric_code="revenue_growth",
        definition_version="metrics-v1",
        period_end=PERIOD_END,
        input_fact_ids=[fact.fact_id],
        input_snapshot={"revenue": "100000000"},
        value=Decimal("0.1"),
        unit="ratio",
        status="calculated",
        calculator_version="deterministic-decimal-v1",
        calculated_at=NOW,
    )
    calculation = Claim(
        claim_id="claim_report_calculation",
        run_id=run.run_id,
        claim_type="calculation",
        text="营业收入增长率为10%。",
        materiality="major",
        status="supported",
        evidence_ids=["ev_report_metric"],
        created_by="financial-analysis-v1",
        created_at=NOW,
    )
    inference = Claim(
        claim_id="claim_report_risk",
        run_id=run.run_id,
        claim_type="inference",
        text="收入增长保持正值，当前未触发收入下降规则。",
        materiality="major",
        status="supported",
        evidence_ids=["ev_report_fact"],
        created_by="risk-detection-v1",
        created_at=NOW,
    )
    limitation = Claim(
        claim_id="claim_report_limitation",
        run_id=run.run_id,
        claim_type="limitation",
        text="本报告仅使用已持久化的工程数据。",
        materiality="minor",
        status="supported",
        evidence_ids=["ev_report_rule"],
        created_by="risk-detection-v1",
        created_at=NOW,
    )
    evidence = [
        Evidence(
            evidence_id="ev_report_metric",
            claim_id=calculation.claim_id,
            evidence_type="metric",
            metric_id=metric.metric_id,
            supports="supports",
            created_at=NOW,
        ),
        Evidence(
            evidence_id="ev_report_fact",
            claim_id=inference.claim_id,
            evidence_type="fact",
            fact_id=fact.fact_id,
            supports="supports",
            created_at=NOW,
        ),
        Evidence(
            evidence_id="ev_report_rule",
            claim_id=limitation.claim_id,
            evidence_type="rule",
            rule_id="R_DATA_LIMITATION_V1",
            supports="qualifies",
            created_at=NOW,
        ),
    ]
    risk = RiskFinding(
        risk_id="risk_report",
        run_id=run.run_id,
        risk_code="R_REPORT_SAMPLE_V1",
        period_end=PERIOD_END,
        category="profitability",
        severity="medium",
        title="示例风险",
        description="示例风险仅用于报告结构测试。",
        claim_ids=[inference.claim_id],
        status="open",
        limitations=[],
        confidence=Decimal("0.8500"),
        created_at=NOW,
    )
    return (
        run,
        [fact],
        [metric],
        [calculation, inference, limitation],
        evidence,
        [risk],
        [source],
    )


def test_builds_versioned_report_sections_and_source_refs() -> None:
    content, claim_ids = build_report_content(*_inputs())

    assert content["schema_version"] == REPORT_SCHEMA_VERSION
    assert set(content) == {
        "schema_version",
        "run",
        "facts",
        "calculations",
        "inferences",
        "risks",
        "limitations",
        "evidence",
    }
    assert claim_ids == [
        "claim_report_calculation",
        "claim_report_limitation",
        "claim_report_risk",
    ]
    assert content["facts"][0]["source"]["page_number"] == 12
    assert content["calculations"]["metrics"][0]["value"] == "0.1"
    assert content["evidence"]["ev_report_metric"]["source_refs"][0]["source_id"] == ("src_report")
    assert content["risks"][0]["claim_ids"] == ["claim_report_risk"]
    assert all(
        forbidden not in str(content) for forbidden in ("买入", "卖出", "目标价", "收益保证")
    )


def test_rejects_unsupported_major_claim() -> None:
    inputs = list(_inputs())
    claims = list(inputs[3])
    claims[0].status = "unsupported"
    inputs[3] = claims

    with pytest.raises(ReportGenerationError, match="supported"):
        build_report_content(*inputs)
