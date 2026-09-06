"""Persistent entities required by the analysis-run lifecycle."""

from __future__ import annotations

from datetime import date, datetime
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
