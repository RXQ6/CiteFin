"""Persistent entities required by the analysis-run lifecycle."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from citefin.db.base import Base


class AnalysisRun(Base):
    """One user-requested financial analysis and its lifecycle state."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_analysis_runs_user_idempotency_key"
        ),
    )

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    security_code: Mapped[str] = mapped_column(String(6), nullable=False)
    report_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    analysis_focus: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_node: Mapped[str | None] = mapped_column(String(64))
    model_profile: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))

    tasks: Mapped[list[Task]] = relationship(back_populates="run", cascade="all, delete-orphan")
    audit_events: Mapped[list[AuditEvent]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    checkpoints: Mapped[list[WorkflowCheckpoint]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    source_documents: Mapped[list[SourceDocument]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    financial_facts: Mapped[list[FinancialFact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    calculated_metrics: Mapped[list[CalculatedMetric]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    claims: Mapped[list[Claim]] = relationship(back_populates="run", cascade="all, delete-orphan")
    risk_findings: Mapped[list[RiskFinding]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    reports: Mapped[list[Report]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    goal_gate_decisions: Mapped[list[GoalGateDecision]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class Task(Base):
    """A persistent, machine-verifiable unit in the runtime task graph."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_id: Mapped[str] = mapped_column(String(16), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128))
    blocked_by: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_rule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[AnalysisRun] = relationship(back_populates="tasks")


class AuditEvent(Base):
    """Append-only evidence of a lifecycle transition or tool action."""

    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="audit_events")


class WorkflowCheckpoint(Base):
    """A durable LangGraph recovery boundary that references business truth."""

    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "state_version", name="uq_workflow_checkpoints_run_state_version"
        ),
    )

    checkpoint_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_uri: Mapped[str] = mapped_column(Text, nullable=False)
    state_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="checkpoints")


class StoredObject(Base):
    """One immutable, globally deduplicated binary object."""

    __tablename__ = "stored_objects"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    documents: Mapped[list[SourceDocument]] = relationship(back_populates="stored_object")


class SourceDocument(Base):
    """A run-scoped reference to an immutable annual-report object."""

    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("run_id", "sha256", name="uq_source_documents_run_id_sha256"),
    )

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(
        ForeignKey("stored_objects.sha256", ondelete="RESTRICT"), nullable=False, index=True
    )
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200))
    security_code: Mapped[str | None] = mapped_column(String(6))
    period_end: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text_extractable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="source_documents")
    stored_object: Mapped[StoredObject] = relationship(back_populates="documents")
    pages: Mapped[list[DocumentPage]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    statement_identifications: Mapped[list[StatementIdentification]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    financial_facts: Mapped[list[FinancialFact]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )


class FinancialFact(Base):
    """A versioned, source-linked fact normalized from an identified statement row."""

    __tablename__ = "financial_facts"
    __table_args__ = (
        CheckConstraint(
            "statement_type IN ('balance_sheet', 'income_statement', 'cashflow_statement')",
            name="financial_fact_statement_type_allowed",
        ),
        CheckConstraint(
            "period_type IN ('instant', 'duration')",
            name="financial_fact_period_type_allowed",
        ),
        CheckConstraint(
            "scope = 'consolidated'",
            name="financial_fact_scope_consolidated",
        ),
        CheckConstraint(
            "display_unit IN ('yuan', 'thousand_yuan', 'million_yuan')",
            name="financial_fact_display_unit_allowed",
        ),
        CheckConstraint(
            "validation_status IN ('extracted', 'conflict')",
            name="financial_fact_validation_status_allowed",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="financial_fact_confidence_range",
        ),
    )

    fact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.source_id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    concept: Mapped[str] = mapped_column(String(96), nullable=False)
    label_raw: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    display_unit: Mapped[str] = mapped_column(String(24), nullable=False)
    raw_value: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False)
    normalized_value: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False)
    sign_convention: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(200), nullable=False)
    table_id: Mapped[str | None] = mapped_column(String(64))
    row_label: Mapped[str] = mapped_column(Text, nullable=False)
    column_label: Mapped[str] = mapped_column(Text, nullable=False)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)
    extraction_method: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    mapping_version: Mapped[str] = mapped_column(String(64), nullable=False)
    identity_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    conflict_group_id: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="financial_facts")
    source_document: Mapped[SourceDocument] = relationship(back_populates="financial_facts")


class CalculatedMetric(Base):
    """One versioned, source-fact-backed deterministic metric result."""

    __tablename__ = "calculated_metrics"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "metric_code", "period_end", name="uq_calculated_metrics_run_code_period"
        ),
        CheckConstraint(
            "status IN ('calculated', 'missing_input', 'zero_denominator', 'conflict')",
            name="calculated_metric_status_allowed",
        ),
    )

    metric_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    definition_version: Mapped[str] = mapped_column(String(64), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    input_fact_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 16))
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    calculator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="calculated_metrics")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="metric")


class Claim(Base):
    """One atomic statement that may be supported by one or more evidence items."""

    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(
            "claim_type IN ('fact', 'calculation', 'inference', 'limitation')",
            name="claim_type_allowed",
        ),
        CheckConstraint("materiality IN ('major', 'minor')", name="claim_materiality_allowed"),
        CheckConstraint(
            "status IN ('draft', 'supported', 'unsupported', 'rejected')",
            name="claim_status_allowed",
        ),
    )

    claim_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    materiality: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="claims")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="claim", cascade="all, delete-orphan"
    )


class Evidence(Base):
    """A single auditable link from a claim to one source, fact, metric, or rule."""

    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "evidence_type IN ('source_locator', 'fact', 'metric', 'rule')",
            name="evidence_type_allowed",
        ),
        CheckConstraint(
            "supports IN ('supports', 'contradicts', 'qualifies')",
            name="evidence_supports_allowed",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.claim_id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.source_id", ondelete="CASCADE"), index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    fact_id: Mapped[str | None] = mapped_column(
        ForeignKey("financial_facts.fact_id", ondelete="CASCADE"), index=True
    )
    metric_id: Mapped[str | None] = mapped_column(
        ForeignKey("calculated_metrics.metric_id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str | None] = mapped_column(String(128))
    excerpt: Mapped[str | None] = mapped_column(Text)
    supports: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    claim: Mapped[Claim] = relationship(back_populates="evidence")
    source_document: Mapped[SourceDocument | None] = relationship()
    fact: Mapped[FinancialFact | None] = relationship()
    metric: Mapped[CalculatedMetric | None] = relationship(back_populates="evidence")


class RiskFinding(Base):
    """One deterministic, evidence-backed financial risk finding."""

    __tablename__ = "risk_findings"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "risk_code", "period_end", name="uq_risk_findings_run_code_period"
        ),
        CheckConstraint(
            "category IN ("
            "'profitability', 'cashflow', 'solvency', 'working_capital', 'data_quality'"
            ")",
            name="risk_finding_category_allowed",
        ),
        CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name="risk_finding_severity_allowed",
        ),
        CheckConstraint(
            "status IN ('open', 'qualified', 'dismissed')",
            name="risk_finding_status_allowed",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="risk_finding_confidence_range",
        ),
    )

    risk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    risk_code: Mapped[str] = mapped_column(String(128), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    limitations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="risk_findings")


class Report(Base):
    """One versioned, structured report assembled from persisted evidence."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_reports_run_version"),
        CheckConstraint(
            "status IN ('draft', 'candidate', 'verified', 'superseded')",
            name="report_status_allowed",
        ),
    )

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="reports")
    evaluations: Mapped[list[Evaluation]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class Evaluation(Base):
    """One independent, auditable evaluation of a persisted report candidate."""

    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("report_id", "evaluator_version", name="uq_evaluations_report_evaluator"),
        CheckConstraint(
            "status IN ('passed', 'failed', 'error')",
            name="evaluation_status_allowed",
        ),
    )

    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluator_version: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    blocking_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    node_hint: Mapped[str | None] = mapped_column(String(64))
    repair_instruction: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="evaluations")
    report: Mapped[Report] = relationship(back_populates="evaluations")


class GoalGateDecision(Base):
    """One auditable terminal decision made from an independent evaluation."""

    __tablename__ = "goal_gate_decisions"
    __table_args__ = (
        UniqueConstraint("report_id", "gate_version", name="uq_goal_gate_report_version"),
        CheckConstraint(
            "decision IN ('verified', 'revision_required', 'blocked', 'error')",
            name="goal_gate_decision_allowed",
        ),
    )

    gate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_runs.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("reports.report_id", ondelete="CASCADE"), nullable=False, index=True
    )
    evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluations.evaluation_id", ondelete="SET NULL"), index=True
    )
    gate_version: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    blocking_reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    node_hint: Mapped[str | None] = mapped_column(String(64))
    repair_instruction: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[AnalysisRun] = relationship(back_populates="goal_gate_decisions")
    report: Mapped[Report] = relationship()
    evaluation: Mapped[Evaluation | None] = relationship()


class DocumentPage(Base):
    """Immutable page-level text, locator index, and structured parse outcome."""

    __tablename__ = "document_pages"
    __table_args__ = (CheckConstraint("page_number >= 1", name="page_number_positive"),)

    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.source_id", ondelete="CASCADE"), primary_key=True
    )
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    bbox_index_uri: Mapped[str | None] = mapped_column(Text)
    bbox_index_sha256: Mapped[str | None] = mapped_column(
        ForeignKey("stored_objects.sha256", ondelete="RESTRICT")
    )
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_document: Mapped[SourceDocument] = relationship(back_populates="pages")
    bbox_index_object: Mapped[StoredObject | None] = relationship()


class StatementIdentification(Base):
    """One durable F004 outcome for a required financial statement type."""

    __tablename__ = "statement_identifications"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "statement_type", name="uq_statement_identifications_source_type"
        ),
        CheckConstraint(
            "statement_type IN ('balance_sheet', 'income_statement', 'cashflow_statement')",
            name="statement_type_allowed",
        ),
    )

    statement_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.source_id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    period_end: Mapped[date | None] = mapped_column(Date)
    page_number: Mapped[int | None] = mapped_column(Integer)
    table_id: Mapped[str | None] = mapped_column(String(64))
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    reason: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source_document: Mapped[SourceDocument] = relationship(
        back_populates="statement_identifications"
    )
