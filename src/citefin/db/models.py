"""Persistent entities required by the analysis-run lifecycle."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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
