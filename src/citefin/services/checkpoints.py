"""Versioned, source-integrity-checked workflow checkpoint persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    GoalGateDecision,
    SourceDocument,
    WorkflowCheckpoint,
)
from citefin.ids import new_prefixed_id
from citefin.workflow import WORKFLOW_VERSION, FinanceAgentState


class CheckpointError(ValueError):
    """A stable, actionable checkpoint persistence or recovery failure."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class CheckpointSave:
    """A newly saved or idempotently replayed checkpoint."""

    checkpoint: WorkflowCheckpoint
    state: FinanceAgentState
    idempotent_replay: bool


@dataclass(frozen=True)
class CheckpointRestore:
    """A validated state ready for a workflow executor to resume."""

    checkpoint: WorkflowCheckpoint
    state: FinanceAgentState
    idempotent_replay: bool


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.run_id == run_id,
            AnalysisRun.user_id == user_id,
        )
    )
    if run is None:
        raise CheckpointError("analysis_run_not_found", "Analysis run was not found.", 404)
    return run


def _validate_workflow_version(run: AnalysisRun, state: FinanceAgentState) -> None:
    if (
        run.workflow_version != WORKFLOW_VERSION
        or state.workflow_version != WORKFLOW_VERSION
        or state.workflow_version != run.workflow_version
    ):
        raise CheckpointError(
            "workflow_version_mismatch",
            "Checkpoint workflow version does not match the active run workflow.",
            409,
        )


def _source_hash_snapshot(
    session: Session,
    run_id: str,
    source_ids: list[str],
    supplied_hashes: dict[str, str] | None = None,
) -> dict[str, str]:
    """Resolve and verify immutable source hashes owned by this run."""

    unique_source_ids = list(dict.fromkeys(source_ids))
    if len(unique_source_ids) != len(source_ids):
        raise CheckpointError(
            "duplicate_source_reference",
            "Checkpoint source_ids must not contain duplicates.",
        )
    documents = session.scalars(
        select(SourceDocument).where(
            SourceDocument.run_id == run_id,
            SourceDocument.source_id.in_(unique_source_ids),
        )
    ).all()
    by_id = {document.source_id: document for document in documents}
    missing = [source_id for source_id in unique_source_ids if source_id not in by_id]
    if missing:
        raise CheckpointError(
            "source_not_found",
            "Checkpoint references a source document that is not owned by the run.",
            404,
        )
    current_hashes = {source_id: by_id[source_id].sha256 for source_id in unique_source_ids}
    if supplied_hashes and supplied_hashes != current_hashes:
        raise CheckpointError(
            "source_hash_mismatch",
            "Checkpoint source hashes do not match the immutable source records.",
            409,
        )
    return current_hashes


def _validate_verified_state(session: Session, state: FinanceAgentState) -> None:
    if state.status != "verified":
        return
    decision = session.scalar(
        select(GoalGateDecision).where(
            GoalGateDecision.run_id == state.run_id,
            GoalGateDecision.decision == "verified",
        )
    )
    if decision is None or state.current_node.value != "finalize":
        raise CheckpointError(
            "verified_requires_goal_gate",
            "Only a verified Goal Gate decision may persist a verified checkpoint.",
        )


def _checkpoint_state_data(state: FinanceAgentState) -> dict[str, Any]:
    return state.model_dump(mode="json")


def _same_checkpoint(checkpoint: WorkflowCheckpoint, state: FinanceAgentState) -> bool:
    return (
        checkpoint.run_id == state.run_id
        and checkpoint.thread_id == state.thread_id
        and checkpoint.node == state.current_node.value
        and checkpoint.state_version == state.state_version
        and checkpoint.state_data == _checkpoint_state_data(state)
    )


def save_checkpoint(
    session: Session,
    state: FinanceAgentState,
    user_id: str,
    *,
    thread_id: str | None = None,
) -> CheckpointSave:
    """Persist one immutable version or replay the exact same version safely."""

    run = _owned_run(session, state.run_id, user_id)
    _validate_workflow_version(run, state)
    if thread_id is not None and state.thread_id not in (None, thread_id):
        raise CheckpointError(
            "thread_id_mismatch",
            "Checkpoint thread_id does not match the supplied workflow thread.",
        )
    initial_checkpoint = session.scalar(
        select(WorkflowCheckpoint)
        .where(WorkflowCheckpoint.run_id == state.run_id)
        .order_by(WorkflowCheckpoint.state_version)
    )
    resolved_thread_id = (
        thread_id
        or state.thread_id
        or (initial_checkpoint.thread_id if initial_checkpoint is not None else None)
    )
    if resolved_thread_id is None:
        raise CheckpointError("thread_id_required", "Checkpoint thread_id is required.")
    source_hashes = _source_hash_snapshot(
        session, state.run_id, state.source_ids, state.source_hashes
    )
    normalized_state = state.model_copy(
        update={"thread_id": resolved_thread_id, "source_hashes": source_hashes}
    )
    _validate_verified_state(session, normalized_state)

    existing = session.scalar(
        select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.run_id == state.run_id,
            WorkflowCheckpoint.state_version == state.state_version,
        )
    )
    if existing is not None:
        if _same_checkpoint(existing, normalized_state):
            return CheckpointSave(existing, normalized_state, True)
        raise CheckpointError(
            "checkpoint_version_conflict",
            "A different state is already stored at this state_version.",
            409,
        ) from None
    latest_version = session.scalar(
        select(func.max(WorkflowCheckpoint.state_version)).where(
            WorkflowCheckpoint.run_id == state.run_id
        )
    )
    if latest_version is not None and state.state_version <= latest_version:
        raise CheckpointError(
            "state_version_regression",
            "New checkpoints must advance the run state_version.",
            409,
        )

    now = datetime.now(UTC)
    checkpoint = WorkflowCheckpoint(
        checkpoint_id=new_prefixed_id("checkpoint"),
        run_id=state.run_id,
        thread_id=resolved_thread_id,
        node=normalized_state.current_node.value,
        state_version=normalized_state.state_version,
        state_uri=f"db://workflow_checkpoints/{state.run_id}/{normalized_state.state_version}",
        state_data=_checkpoint_state_data(normalized_state),
        created_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=state.run_id,
        trace_id=new_prefixed_id("trace"),
        node=normalized_state.current_node.value,
        event_type="checkpoint_saved",
        status="success",
        payload={
            "checkpoint_id": checkpoint.checkpoint_id,
            "state_version": normalized_state.state_version,
            "node": normalized_state.current_node.value,
            "source_ids": normalized_state.source_ids,
        },
        created_at=now,
    )
    session.add_all([checkpoint, event])
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(WorkflowCheckpoint).where(
                WorkflowCheckpoint.run_id == state.run_id,
                WorkflowCheckpoint.state_version == state.state_version,
            )
        )
        if concurrent is not None and _same_checkpoint(concurrent, normalized_state):
            return CheckpointSave(concurrent, normalized_state, True)
        raise CheckpointError(
            "checkpoint_version_conflict",
            "A different state is already stored at this state_version.",
            409,
        ) from None
    return CheckpointSave(checkpoint, normalized_state, False)


def _restore_audit_exists(session: Session, run_id: str, checkpoint_id: str) -> bool:
    events = session.scalars(
        select(AuditEvent).where(
            AuditEvent.run_id == run_id,
            AuditEvent.event_type == "checkpoint_restored",
        )
    )
    return any(event.payload.get("checkpoint_id") == checkpoint_id for event in events)


def restore_checkpoint(
    session: Session,
    run_id: str,
    checkpoint_id: str,
    user_id: str,
) -> CheckpointRestore:
    """Validate one owned checkpoint and apply its control state idempotently."""

    run = _owned_run(session, run_id, user_id)
    checkpoint = session.scalar(
        select(WorkflowCheckpoint).where(
            WorkflowCheckpoint.checkpoint_id == checkpoint_id,
            WorkflowCheckpoint.run_id == run_id,
        )
    )
    if checkpoint is None:
        raise CheckpointError("checkpoint_not_found", "Workflow checkpoint was not found.", 404)
    try:
        state = FinanceAgentState.model_validate(checkpoint.state_data)
    except ValidationError as error:
        raise CheckpointError(
            "invalid_checkpoint_state",
            "Stored checkpoint state does not satisfy the workflow state contract.",
            409,
        ) from error
    _validate_workflow_version(run, state)
    if state.run_id != run_id:
        raise CheckpointError("checkpoint_run_mismatch", "Checkpoint run_id is inconsistent.", 409)
    if state.thread_id != checkpoint.thread_id:
        raise CheckpointError(
            "checkpoint_thread_mismatch",
            "Checkpoint thread_id is inconsistent.",
            409,
        )
    if state.current_node.value != checkpoint.node:
        raise CheckpointError("checkpoint_node_mismatch", "Checkpoint node is inconsistent.", 409)
    if state.state_version != checkpoint.state_version:
        raise CheckpointError(
            "checkpoint_state_version_mismatch",
            "Checkpoint state_version is inconsistent.",
            409,
        )
    _source_hash_snapshot(session, run_id, state.source_ids, state.source_hashes)
    _validate_verified_state(session, state)

    replay = _restore_audit_exists(session, run_id, checkpoint_id)
    if not replay:
        now = datetime.now(UTC)
        run.current_node = state.current_node.value
        run.status = state.status
        run.updated_at = now
        session.add(
            AuditEvent(
                event_id=new_prefixed_id("event"),
                run_id=run_id,
                trace_id=new_prefixed_id("trace"),
                node=state.current_node.value,
                event_type="checkpoint_restored",
                status="success",
                payload={
                    "checkpoint_id": checkpoint_id,
                    "state_version": state.state_version,
                    "node": state.current_node.value,
                },
                created_at=now,
            )
        )
        session.commit()
    return CheckpointRestore(checkpoint, state, replay)
