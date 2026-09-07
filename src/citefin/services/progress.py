"""User-scoped run progress and replayable lifecycle-event queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from citefin.db.models import AnalysisRun, AuditEvent, Task

_ERROR_STATUSES = {"failed", "error", "blocked", "revision_required", "partial_failure"}


class ProgressError(ValueError):
    """A stable, actionable progress-query failure."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class TaskProgress:
    """Safe task fields suitable for a user-facing progress view."""

    task_id: str
    feature_id: str
    task_type: str
    title: str
    status: str
    attempt_count: int
    blocked_by: list[str]
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class ProgressErrorItem:
    """A redacted error summary without internal messages or payload bodies."""

    event_id: str
    node: str
    event_type: str
    status: str
    code: str
    created_at: datetime


@dataclass(frozen=True)
class RunProgress:
    """Owned run state, task summaries, and recent redacted errors."""

    run: AnalysisRun
    tasks: tuple[TaskProgress, ...]
    recent_errors: tuple[ProgressErrorItem, ...]


@dataclass(frozen=True)
class LifecycleEventPage:
    """A finite, ordered page that can be replayed from an event cursor."""

    events: tuple[AuditEvent, ...]
    has_more: bool


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.run_id == run_id,
            AnalysisRun.user_id == user_id,
        )
    )
    if run is None:
        raise ProgressError("analysis_run_not_found", "Analysis run was not found.", 404)
    return run


def _error_code(event: AuditEvent) -> str:
    payload_code = event.payload.get("error_code") or event.payload.get("code")
    return payload_code if isinstance(payload_code, str) else event.event_type


def get_run_progress(
    session: Session,
    run_id: str,
    user_id: str,
    *,
    error_limit: int = 10,
) -> RunProgress:
    """Return only safe, owned lifecycle data for one run."""

    if not 1 <= error_limit <= 50:
        raise ProgressError("invalid_error_limit", "error_limit must be between 1 and 50.")
    run = _owned_run(session, run_id, user_id)
    tasks = session.scalars(select(Task).where(Task.run_id == run_id).order_by(Task.task_id)).all()
    error_events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.run_id == run_id, AuditEvent.status.in_(_ERROR_STATUSES))
        .order_by(desc(AuditEvent.created_at), desc(AuditEvent.event_id))
        .limit(error_limit)
    ).all()
    task_views = tuple(
        TaskProgress(
            task_id=task.task_id,
            feature_id=task.feature_id,
            task_type=task.task_type,
            title=task.title,
            status=task.status,
            attempt_count=task.attempt_count,
            blocked_by=list(task.blocked_by),
            error_code=(
                task.error.get("code")
                if isinstance(task.error, dict) and isinstance(task.error.get("code"), str)
                else None
            ),
            started_at=task.started_at,
            finished_at=task.finished_at,
        )
        for task in tasks
    )
    errors = tuple(
        ProgressErrorItem(
            event_id=event.event_id,
            node=event.node,
            event_type=event.event_type,
            status=event.status,
            code=_error_code(event),
            created_at=event.created_at,
        )
        for event in error_events
    )
    return RunProgress(run=run, tasks=task_views, recent_errors=errors)


def list_lifecycle_events(
    session: Session,
    run_id: str,
    user_id: str,
    *,
    after_event_id: str | None = None,
    limit: int = 100,
) -> LifecycleEventPage:
    """Return an ordered, finite event page after an owned cursor."""

    if not 1 <= limit <= 100:
        raise ProgressError("invalid_event_limit", "limit must be between 1 and 100.")
    _owned_run(session, run_id, user_id)
    cursor = None
    if after_event_id is not None:
        if not after_event_id.startswith("event_"):
            raise ProgressError("invalid_event_cursor", "after_event_id is not valid.")
        cursor = session.scalar(
            select(AuditEvent).where(
                AuditEvent.run_id == run_id,
                AuditEvent.event_id == after_event_id,
            )
        )
        if cursor is None:
            raise ProgressError("invalid_event_cursor", "after_event_id is not valid.")
    statement = select(AuditEvent).where(AuditEvent.run_id == run_id)
    if cursor is not None:
        statement = statement.where(
            or_(
                AuditEvent.created_at > cursor.created_at,
                (AuditEvent.created_at == cursor.created_at)
                & (AuditEvent.event_id > cursor.event_id),
            )
        )
    rows = session.scalars(
        statement.order_by(AuditEvent.created_at, AuditEvent.event_id).limit(limit + 1)
    ).all()
    return LifecycleEventPage(events=tuple(rows[:limit]), has_more=len(rows) > limit)


def safe_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Whitelist non-sensitive lifecycle metadata for the SSE boundary."""

    allowed = {
        "task_id",
        "workflow_version",
        "from_node",
        "to_node",
        "checkpoint_id",
        "state_version",
        "node",
        "source_id",
        "page_count",
        "failed_page_count",
        "storage_reused",
        "evaluation_id",
        "report_id",
        "gate_id",
        "decision",
        "metric_count",
        "risk_count",
        "claim_count",
        "evidence_count",
        "check_count",
        "blocking_count",
        "feature_id",
        "period_end",
        "status",
        "error_code",
        "node_hint",
    }
    return {key: value for key, value in payload.items() if key in allowed}
