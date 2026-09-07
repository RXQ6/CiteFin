"""Typed workflow state, deterministic routing, and audit-boundary helpers."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import AnalysisRun, AuditEvent
from citefin.ids import new_prefixed_id

WORKFLOW_VERSION = "1.1.0"


class WorkflowNode(StrEnum):
    """Nodes that may appear in the persisted control state."""

    CREATE_RUN = "create_run"
    REQUEST_GUARD = "request_guard"
    DOCUMENT_PARSE = "document_parse"
    STATEMENT_EXTRACT = "statement_extract"
    NORMALIZE_FACTS = "normalize_facts"
    DATA_QUALITY_GATE = "data_quality_gate"
    CALCULATE_METRICS = "calculate_metrics"
    ANALYZE_FINANCIALS = "analyze_financials"
    DETECT_RISKS = "detect_risks"
    BUILD_EVIDENCE_MAP = "build_evidence_map"
    WRITE_REPORT = "write_report"
    GOAL_EVALUATOR = "goal_evaluator"
    REVISION_ROUTER = "revision_router"
    FINALIZE = "finalize"


WorkflowStatus = Literal[
    "created",
    "validating",
    "running",
    "candidate_complete",
    "evaluating",
    "verified",
    "awaiting_user",
    "revision_required",
    "blocked",
    "failed",
]


class FinanceAgentState(BaseModel):
    """Control state containing references only, never PDF or report bodies."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    report_id: str | None = None
    current_node: WorkflowNode
    status: WorkflowStatus
    workflow_version: str = WORKFLOW_VERSION
    state_version: int = Field(default=1, ge=1)
    as_of: datetime
    last_error: dict[str, Any] | None = None


class WorkflowError(Exception):
    """Stable error for invalid workflow transitions or ownership."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def route_after_data_quality(
    *, passed: bool, needs_user_confirmation: bool = False
) -> WorkflowNode:
    """Route data-quality outcomes without hiding a missing or ambiguous input."""

    if passed:
        return WorkflowNode.CALCULATE_METRICS
    if needs_user_confirmation:
        return WorkflowNode.REQUEST_GUARD
    return WorkflowNode.REVISION_ROUTER


def route_after_evaluator(*, passed: bool, needs_revision: bool = False) -> WorkflowNode:
    """Route evaluator outcomes; only a later Goal Gate may finalize verified state."""

    if passed:
        return WorkflowNode.FINALIZE
    if needs_revision:
        return WorkflowNode.REVISION_ROUTER
    return WorkflowNode.GOAL_EVALUATOR


def _can_transition(current: WorkflowNode, target: WorkflowNode) -> bool:
    if current == target:
        return True
    if current == WorkflowNode.CREATE_RUN:
        return target == WorkflowNode.REQUEST_GUARD
    if current == WorkflowNode.REQUEST_GUARD:
        return target in {WorkflowNode.DOCUMENT_PARSE, WorkflowNode.REVISION_ROUTER}
    if current == WorkflowNode.DOCUMENT_PARSE:
        return target == WorkflowNode.STATEMENT_EXTRACT
    if current == WorkflowNode.STATEMENT_EXTRACT:
        return target == WorkflowNode.NORMALIZE_FACTS
    if current == WorkflowNode.NORMALIZE_FACTS:
        return target == WorkflowNode.DATA_QUALITY_GATE
    if current == WorkflowNode.DATA_QUALITY_GATE:
        return target in {WorkflowNode.CALCULATE_METRICS, WorkflowNode.REVISION_ROUTER}
    if current == WorkflowNode.CALCULATE_METRICS:
        return target == WorkflowNode.ANALYZE_FINANCIALS
    if current == WorkflowNode.ANALYZE_FINANCIALS:
        return target == WorkflowNode.DETECT_RISKS
    if current == WorkflowNode.DETECT_RISKS:
        return target == WorkflowNode.BUILD_EVIDENCE_MAP
    if current == WorkflowNode.BUILD_EVIDENCE_MAP:
        return target == WorkflowNode.WRITE_REPORT
    if current == WorkflowNode.WRITE_REPORT:
        return target == WorkflowNode.GOAL_EVALUATOR
    if current == WorkflowNode.GOAL_EVALUATOR:
        return target in {WorkflowNode.REVISION_ROUTER, WorkflowNode.FINALIZE}
    if current == WorkflowNode.REVISION_ROUTER:
        return target in {
            WorkflowNode.REQUEST_GUARD,
            WorkflowNode.CALCULATE_METRICS,
            WorkflowNode.WRITE_REPORT,
        }
    return current == WorkflowNode.FINALIZE and target == WorkflowNode.FINALIZE


def advance_state(
    session: Session,
    state: FinanceAgentState,
    user_id: str,
    next_node: WorkflowNode,
    *,
    status: WorkflowStatus = "running",
    event_type: str = "node_transition",
    payload: dict[str, Any] | None = None,
) -> FinanceAgentState:
    """Persist an owned node transition and return the next immutable state value."""

    run = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.run_id == state.run_id, AnalysisRun.user_id == user_id
        )
    )
    if run is None:
        raise WorkflowError("run_not_found", "Analysis run was not found.", 404)
    if not _can_transition(state.current_node, next_node):
        raise WorkflowError(
            "invalid_node_transition",
            f"Cannot transition from {state.current_node} to {next_node}.",
        )
    if status == "verified" and (
        state.current_node != WorkflowNode.GOAL_EVALUATOR
        or next_node != WorkflowNode.FINALIZE
        or event_type != "goal_gate_verified"
    ):
        raise WorkflowError(
            "verified_requires_goal_gate",
            "Only Goal Gate may transition an evaluated run to verified.",
        )
    now = datetime.now(run.as_of.tzinfo)
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=state.run_id,
        trace_id=new_prefixed_id("trace"),
        node=next_node.value,
        event_type=event_type,
        status="success",
        payload={
            "from_node": state.current_node.value,
            "to_node": next_node.value,
            **(payload or {}),
        },
        created_at=now,
    )
    run.current_node = next_node.value
    run.status = status
    run.updated_at = now
    session.add(event)
    session.commit()
    return state.model_copy(
        update={
            "current_node": next_node,
            "status": status,
            "state_version": state.state_version + 1,
        }
    )
