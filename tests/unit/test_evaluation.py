"""Tests for the independent, deterministic F012 evaluator."""

from datetime import UTC, date, datetime
from decimal import Decimal

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    CalculatedMetric,
    Claim,
    Evidence,
    FinancialFact,
    Report,
    RiskFinding,
    SourceDocument,
)
from citefin.services.evaluation import _evaluate_checks, _input_snapshot
from citefin.services.report_generation import build_report_content

NOW = datetime(2026, 9, 7, tzinfo=UTC)
PERIOD_END = date(2025, 12, 31)


def _bundle() -> tuple[
    Report,
    list[FinancialFact],
    list[CalculatedMetric],
    list[Claim],
    list[Evidence],
    list[RiskFinding],
    list[AuditEvent],
]:
    run = AnalysisRun(
        run_id="run_evaluation",
        idempotency_key="evaluation-key",
        user_id="evaluation-user",
        company_name="评测示例股份有限公司",
        security_code="600006",
        report_period_end=PERIOD_END,
        as_of=NOW,
        analysis_focus=["comprehensive"],
        status="candidate_complete",
        current_node="write_report",
        model_profile="deterministic-test",
        workflow_version="1.1.0",
        created_at=NOW,
        updated_at=NOW,
    )
    source = SourceDocument(
        source_id="src_evaluation",
        run_id=run.run_id,
        document_type="annual_report",
        file_name="evaluation.pdf",
        media_type="application/pdf",
        sha256="f" * 64,
        storage_uri="object://" + "f" * 64,
        language="zh-CN",
        page_count=1,
        text_extractable=True,
        parser_version="test",
        ingested_at=NOW,
    )
    fact = FinancialFact(
        fact_id="fact_evaluation_revenue",
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
        identity_key="evaluation-revenue",
        created_at=NOW,
    )
    metric = CalculatedMetric(
        metric_id="metric_evaluation_revenue",
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
        claim_id="claim_evaluation_calculation",
        run_id=run.run_id,
        claim_type="calculation",
        text="营业收入增长率为10%。",
        materiality="major",
        status="supported",
        evidence_ids=["ev_evaluation_metric"],
        created_by="financial-analysis-v1",
        created_at=NOW,
    )
    inference = Claim(
        claim_id="claim_evaluation_inference",
        run_id=run.run_id,
        claim_type="inference",
        text="收入增长保持正值。",
        materiality="major",
        status="supported",
        evidence_ids=["ev_evaluation_fact"],
        created_by="risk-detection-v1",
        created_at=NOW,
    )
    limitation = Claim(
        claim_id="claim_evaluation_limitation",
        run_id=run.run_id,
        claim_type="limitation",
        text="本评测仅使用契约输入。",
        materiality="minor",
        status="supported",
        evidence_ids=["ev_evaluation_rule"],
        created_by="risk-detection-v1",
        created_at=NOW,
    )
    evidence = [
        Evidence(
            evidence_id="ev_evaluation_metric",
            claim_id=calculation.claim_id,
            evidence_type="metric",
            metric_id=metric.metric_id,
            supports="supports",
            created_at=NOW,
        ),
        Evidence(
            evidence_id="ev_evaluation_fact",
            claim_id=inference.claim_id,
            evidence_type="fact",
            fact_id=fact.fact_id,
            supports="supports",
            created_at=NOW,
        ),
        Evidence(
            evidence_id="ev_evaluation_rule",
            claim_id=limitation.claim_id,
            evidence_type="rule",
            rule_id="R_EVALUATION_LIMITATION_V1",
            supports="qualifies",
            created_at=NOW,
        ),
    ]
    risk = RiskFinding(
        risk_id="risk_evaluation",
        run_id=run.run_id,
        risk_code="R_EVALUATION_SAMPLE_V1",
        period_end=PERIOD_END,
        category="profitability",
        severity="medium",
        title="示例风险",
        description="示例风险仅用于评测结构测试。",
        claim_ids=[inference.claim_id],
        status="open",
        limitations=[],
        confidence=Decimal("0.8500"),
        created_at=NOW,
    )
    content, claim_ids = build_report_content(
        run,
        [fact],
        [metric],
        [calculation, inference, limitation],
        evidence,
        [risk],
        [source],
    )
    report = Report(
        report_id="report_evaluation",
        run_id=run.run_id,
        version=1,
        status="candidate",
        schema_version="financial-report-v1",
        content=content,
        claim_ids=claim_ids,
        generated_by="deterministic-report-v1",
        created_at=NOW,
    )
    audit_event = AuditEvent(
        event_id="event_evaluation_report",
        run_id=run.run_id,
        trace_id="trace_evaluation_report",
        node="write_report",
        event_type="report_candidate_generated",
        status="success",
        payload={"report_id": report.report_id},
        created_at=NOW,
    )
    return (
        report,
        [fact],
        [metric],
        [calculation, inference, limitation],
        evidence,
        [risk],
        [audit_event],
    )


def test_evaluator_passes_auditable_report_bundle() -> None:
    report, facts, metrics, claims, evidence, risks, audit_events = _bundle()
    checks = _evaluate_checks(
        report, report.content, facts, metrics, claims, evidence, risks, audit_events
    )

    assert {check["code"] for check in checks} == {
        "report_schema",
        "claim_evidence_coverage",
        "evidence_referential_integrity",
        "metric_lineage",
        "risk_traceability",
        "compliance_wording",
        "audit_completeness",
    }
    assert all(check["result"] == "passed" for check in checks)
    snapshot = _input_snapshot(
        report, report.content, facts, metrics, claims, evidence, risks, audit_events
    )
    assert snapshot["report_content_sha256"]
    assert snapshot["entity_counts"] == {
        "facts": 1,
        "metrics": 1,
        "claims": 3,
        "evidence": 3,
        "risks": 1,
        "audit_events": 1,
    }


def test_evaluator_returns_repair_routing_for_missing_major_evidence() -> None:
    report, facts, metrics, claims, evidence, risks, audit_events = _bundle()
    report.content["evidence"].pop("ev_evaluation_metric")
    checks = _evaluate_checks(
        report, report.content, facts, metrics, claims, evidence, risks, audit_events
    )

    coverage = next(check for check in checks if check["code"] == "claim_evidence_coverage")
    assert coverage["result"] == "failed"
    assert coverage["node_hint"] == "build_evidence_map"
    assert coverage["repair_instruction"]
