"""Tests for F008 typed workflow state and deterministic routing."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from citefin.workflow import (
    FinanceAgentState,
    WorkflowNode,
    _can_transition,
    route_after_data_quality,
    route_after_evaluator,
)


def _state() -> FinanceAgentState:
    return FinanceAgentState(
        run_id="run_test",
        task_id="task_test",
        current_node=WorkflowNode.DATA_QUALITY_GATE,
        status="running",
        as_of=datetime(2026, 9, 7, tzinfo=UTC),
    )


def test_state_contains_references_and_rejects_report_body() -> None:
    state = _state()
    assert state.model_dump()["source_ids"] == []
    with pytest.raises(ValidationError):
        FinanceAgentState(**{**state.model_dump(), "report_body": "raw report"})


def test_data_quality_and_evaluator_routes_are_explicit() -> None:
    assert route_after_data_quality(passed=True) == WorkflowNode.CALCULATE_METRICS
    assert (
        route_after_data_quality(passed=False, needs_user_confirmation=True)
        == WorkflowNode.REQUEST_GUARD
    )
    assert route_after_data_quality(passed=False) == WorkflowNode.REVISION_ROUTER
    assert route_after_evaluator(passed=True) == WorkflowNode.FINALIZE
    assert route_after_evaluator(passed=False, needs_revision=True) == WorkflowNode.REVISION_ROUTER
    assert route_after_evaluator(passed=False) == WorkflowNode.GOAL_EVALUATOR


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (WorkflowNode.CREATE_RUN, WorkflowNode.REQUEST_GUARD),
        (WorkflowNode.REQUEST_GUARD, WorkflowNode.DOCUMENT_PARSE),
        (WorkflowNode.REQUEST_GUARD, WorkflowNode.REVISION_ROUTER),
        (WorkflowNode.DOCUMENT_PARSE, WorkflowNode.STATEMENT_EXTRACT),
        (WorkflowNode.STATEMENT_EXTRACT, WorkflowNode.NORMALIZE_FACTS),
        (WorkflowNode.NORMALIZE_FACTS, WorkflowNode.DATA_QUALITY_GATE),
        (WorkflowNode.DATA_QUALITY_GATE, WorkflowNode.CALCULATE_METRICS),
        (WorkflowNode.DATA_QUALITY_GATE, WorkflowNode.REVISION_ROUTER),
        (WorkflowNode.CALCULATE_METRICS, WorkflowNode.ANALYZE_FINANCIALS),
        (WorkflowNode.ANALYZE_FINANCIALS, WorkflowNode.DETECT_RISKS),
        (WorkflowNode.DETECT_RISKS, WorkflowNode.BUILD_EVIDENCE_MAP),
        (WorkflowNode.BUILD_EVIDENCE_MAP, WorkflowNode.WRITE_REPORT),
        (WorkflowNode.WRITE_REPORT, WorkflowNode.GOAL_EVALUATOR),
        (WorkflowNode.GOAL_EVALUATOR, WorkflowNode.REVISION_ROUTER),
        (WorkflowNode.GOAL_EVALUATOR, WorkflowNode.FINALIZE),
        (WorkflowNode.REVISION_ROUTER, WorkflowNode.REQUEST_GUARD),
        (WorkflowNode.REVISION_ROUTER, WorkflowNode.CALCULATE_METRICS),
        (WorkflowNode.REVISION_ROUTER, WorkflowNode.WRITE_REPORT),
        (WorkflowNode.FINALIZE, WorkflowNode.FINALIZE),
    ],
)
def test_allowed_workflow_transitions_are_explicit(
    current: WorkflowNode, target: WorkflowNode
) -> None:
    assert _can_transition(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (WorkflowNode.CREATE_RUN, WorkflowNode.DOCUMENT_PARSE),
        (WorkflowNode.DATA_QUALITY_GATE, WorkflowNode.WRITE_REPORT),
        (WorkflowNode.FINALIZE, WorkflowNode.REQUEST_GUARD),
    ],
)
def test_disallowed_workflow_transitions_are_rejected(
    current: WorkflowNode, target: WorkflowNode
) -> None:
    assert _can_transition(current, target) is False
