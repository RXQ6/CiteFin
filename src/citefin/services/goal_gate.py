"""The only service allowed to make a verified Goal Gate decision."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    Evaluation,
    GoalGateDecision,
    Report,
)
from citefin.ids import new_prefixed_id

GOAL_GATE_VERSION = "deterministic-goal-gate-v1"
_REQUIRED_EVALUATION_CHECKS = {
    "report_schema",
    "claim_evidence_coverage",
    "evidence_referential_integrity",
    "metric_lineage",
    "risk_traceability",
    "compliance_wording",
    "audit_completeness",
}


class GoalGateError(Exception):
    """Stable error raised at the Goal Gate boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class GoalGateResult:
    """Persisted terminal decision and whether the request replayed it."""

    decision: GoalGateDecision
    idempotent_replay: bool


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise GoalGateError("run_not_found", "Analysis run was not found.", 404)
    return run


def _unique(values: Iterable[str]) -> list[str]:
    return sorted(set(values))


def _failure_reason(
    code: str,
    message: str,
    *,
    node_hint: str,
    repair_instruction: str,
    evidence: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "evidence": _unique(evidence),
        "node_hint": node_hint,
        "repair_instruction": repair_instruction,
    }


def _evaluation_evidence(evaluation: Evaluation | None) -> list[str]:
    if evaluation is None:
        return []
    entity_ids = evaluation.input_snapshot.get("entity_ids", {})
    evidence_ids = entity_ids.get("evidence_ids", [])
    return [
        evaluation.evaluation_id,
        *[evidence_id for evidence_id in evidence_ids if isinstance(evidence_id, str)],
    ]


def _repair_instruction(reasons: list[dict[str, Any]]) -> str | None:
    instructions: list[str] = []
    for reason in reasons:
        instruction = reason.get("repair_instruction")
        if isinstance(instruction, str):
            instructions.append(instruction)
    return "；".join(instructions) or None


def decide_goal_gate(session: Session, run_id: str, user_id: str, report_id: str) -> GoalGateResult:
    """Apply the one-way verified decision from an owned report evaluation."""

    run = _owned_run(session, run_id, user_id)
    report = session.scalar(
        select(Report).where(Report.report_id == report_id, Report.run_id == run_id)
    )
    if report is None:
        raise GoalGateError("report_not_found", "Report was not found for this analysis run.", 404)

    existing = session.scalar(
        select(GoalGateDecision).where(
            GoalGateDecision.report_id == report_id,
            GoalGateDecision.gate_version == GOAL_GATE_VERSION,
        )
    )
    if existing is not None:
        return GoalGateResult(existing, True)

    evaluation = session.scalar(
        select(Evaluation)
        .where(Evaluation.run_id == run_id, Evaluation.report_id == report_id)
        .order_by(Evaluation.created_at.desc())
    )
    reasons: list[dict[str, Any]] = []
    node_hint: str | None = None
    decision = "verified"
    if evaluation is None:
        decision = "blocked"
        reasons.append(
            _failure_reason(
                "missing_evaluation",
                "An independent Evaluation is required before Goal Gate completion.",
                node_hint="goal_evaluator",
                repair_instruction=(
                    "Run the independent Evaluator for this report before retrying Goal Gate."
                ),
                evidence=[report.report_id],
            )
        )
        node_hint = "goal_evaluator"
    elif evaluation.status != "passed":
        decision = "revision_required" if evaluation.status == "failed" else "blocked"
        reasons = list(evaluation.blocking_reasons)
        if not reasons:
            reasons = [
                _failure_reason(
                    "evaluation_not_passed",
                    "The independent Evaluation did not pass.",
                    node_hint="goal_evaluator",
                    repair_instruction=(
                        "Inspect the persisted Evaluation and resolve its blocking state."
                    ),
                    evidence=[evaluation.evaluation_id],
                )
            ]
        node_hint = evaluation.node_hint or "goal_evaluator"
    elif {check.get("code") for check in evaluation.checks} != _REQUIRED_EVALUATION_CHECKS or any(
        check.get("result") != "passed" for check in evaluation.checks
    ):
        decision = "blocked"
        reasons = [
            _failure_reason(
                "evaluation_check_mismatch",
                "Evaluation status passed but required persisted checks are incomplete or failed.",
                node_hint="goal_evaluator",
                repair_instruction=(
                    "Reconcile the Evaluation status and its persisted checks before "
                    "retrying Goal Gate."
                ),
                evidence=[evaluation.evaluation_id],
            )
        ]
        node_hint = "goal_evaluator"
    elif report.status != "candidate":
        decision = "blocked"
        reasons = [
            _failure_reason(
                "report_not_candidate",
                "Only a candidate report can be frozen by Goal Gate.",
                node_hint="write_report",
                repair_instruction=(
                    "Create a new candidate report version before retrying Goal Gate."
                ),
                evidence=[report.report_id],
            )
        ]
        node_hint = "write_report"

    if decision == "verified":
        now = datetime.now(UTC)
        report.status = "verified"
        run.status = "verified"
        run.current_node = "finalize"
        run.completed_at = now
        run.failure_code = None
        run.updated_at = now
    else:
        now = datetime.now(UTC)
        run.status = "revision_required" if decision == "revision_required" else "blocked"
        run.current_node = node_hint or "goal_evaluator"
        run.completed_at = None
        run.failure_code = f"goal_gate_{decision}"
        run.updated_at = now

    evidence_refs = _unique([report.report_id, *_evaluation_evidence(evaluation)])
    if reasons:
        evidence_refs = _unique(
            [
                *evidence_refs,
                *[
                    reference
                    for reason in reasons
                    for reference in reason.get("evidence", [])
                    if isinstance(reference, str)
                ],
            ]
        )
    decision_row = GoalGateDecision(
        gate_id=new_prefixed_id("gate"),
        run_id=run_id,
        report_id=report_id,
        evaluation_id=evaluation.evaluation_id if evaluation is not None else None,
        gate_version=GOAL_GATE_VERSION,
        decision=decision,
        evidence_refs=evidence_refs,
        blocking_reasons=reasons,
        node_hint=node_hint,
        repair_instruction=_repair_instruction(reasons),
        created_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="goal_gate",
        event_type="goal_gate_decision",
        status=decision,
        payload={
            "gate_id": decision_row.gate_id,
            "report_id": report_id,
            "evaluation_id": decision_row.evaluation_id,
            "gate_version": GOAL_GATE_VERSION,
            "decision": decision,
            "evidence_refs": evidence_refs,
            "node_hint": node_hint,
        },
        created_at=now,
    )
    session.add_all([decision_row, event])
    session.commit()
    return GoalGateResult(decision_row, False)
