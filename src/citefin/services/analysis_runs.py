"""Transactional creation and idempotent replay of analysis runs."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from citefin.db.models import AnalysisRun, AuditEvent, Task, WorkflowCheckpoint
from citefin.ids import new_prefixed_id


@dataclass(frozen=True)
class CreateAnalysisRunCommand:
    """Validated values needed to create an analysis run."""

    user_id: str
    idempotency_key: str
    company_name: str
    security_code: str
    report_period_end: date
    as_of: datetime
    analysis_focus: list[str]


@dataclass(frozen=True)
class AnalysisRunCreation:
    """Stable identifiers returned for a new or replayed request."""

    run: AnalysisRun
    task_id: str
    event_id: str
    checkpoint_id: str
    thread_id: str
    idempotent_replay: bool


def _existing_creation(session: Session, run: AnalysisRun) -> AnalysisRunCreation:
    task = session.scalar(select(Task).where(Task.run_id == run.run_id).order_by(Task.task_id))
    event = session.scalar(
        select(AuditEvent)
        .where(AuditEvent.run_id == run.run_id, AuditEvent.event_type == "run_created")
        .order_by(AuditEvent.created_at)
    )
    checkpoint = session.scalar(
        select(WorkflowCheckpoint)
        .where(WorkflowCheckpoint.run_id == run.run_id, WorkflowCheckpoint.state_version == 1)
        .order_by(WorkflowCheckpoint.created_at)
    )
    if task is None or event is None or checkpoint is None:
        raise RuntimeError("Existing analysis run is missing its initial persistence bundle")
    return AnalysisRunCreation(
        run=run,
        task_id=task.task_id,
        event_id=event.event_id,
        checkpoint_id=checkpoint.checkpoint_id,
        thread_id=checkpoint.thread_id,
        idempotent_replay=True,
    )


def create_analysis_run(session: Session, command: CreateAnalysisRunCommand) -> AnalysisRunCreation:
    """Atomically create a run bundle or replay its user-scoped idempotent result."""

    existing = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.user_id == command.user_id,
            AnalysisRun.idempotency_key == command.idempotency_key,
        )
    )
    if existing is not None:
        return _existing_creation(session, existing)

    now = datetime.now(UTC)
    run_id = new_prefixed_id("run")
    task_id = new_prefixed_id("task")
    event_id = new_prefixed_id("event")
    checkpoint_id = new_prefixed_id("checkpoint")
    thread_id = new_prefixed_id("thread")
    trace_id = new_prefixed_id("trace")

    run = AnalysisRun(
        run_id=run_id,
        idempotency_key=command.idempotency_key,
        user_id=command.user_id,
        company_name=command.company_name,
        security_code=command.security_code,
        report_period_end=command.report_period_end,
        as_of=command.as_of,
        analysis_focus=command.analysis_focus,
        status="created",
        current_node="create_run",
        model_profile="default-v1",
        workflow_version="1.0.0",
        created_at=now,
        updated_at=now,
    )
    task = Task(
        task_id=task_id,
        run_id=run_id,
        feature_id="CAP-RUN-GUARD",
        task_type="request_validation",
        title="请求与身份校验",
        status="ready",
        blocked_by=[],
        attempt_count=0,
        acceptance_rule={"next_node": "request_guard"},
        evidence_refs=[],
    )
    event = AuditEvent(
        event_id=event_id,
        run_id=run_id,
        trace_id=trace_id,
        node="create_run",
        event_type="run_created",
        status="success",
        payload={"task_id": task_id, "workflow_version": "1.0.0"},
        created_at=now,
    )
    checkpoint = WorkflowCheckpoint(
        checkpoint_id=checkpoint_id,
        run_id=run_id,
        thread_id=thread_id,
        node="create_run",
        state_version=1,
        state_uri=f"db://workflow_checkpoints/{checkpoint_id}",
        state_data={
            "run_id": run_id,
            "thread_id": thread_id,
            "as_of": command.as_of.isoformat(),
            "company": {
                "name": command.company_name,
                "security_code": command.security_code,
                "confirmed": False,
            },
            "report_period": command.report_period_end.isoformat(),
            "tasks": [task_id],
            "current_node": "create_run",
            "status": "created",
        },
        created_at=now,
    )
    session.add_all([run, task, event, checkpoint])

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(AnalysisRun).where(
                AnalysisRun.user_id == command.user_id,
                AnalysisRun.idempotency_key == command.idempotency_key,
            )
        )
        if concurrent is None:
            raise
        return _existing_creation(session, concurrent)

    return AnalysisRunCreation(
        run=run,
        task_id=task_id,
        event_id=event_id,
        checkpoint_id=checkpoint_id,
        thread_id=thread_id,
        idempotent_replay=False,
    )
