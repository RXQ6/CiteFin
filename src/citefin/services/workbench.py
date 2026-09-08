"""Read-only projections for the user-facing analysis workbench."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    CalculatedMetric,
    Claim,
    Evaluation,
    FinancialFact,
    GoalGateDecision,
    Report,
    RiskFinding,
    SourceDocument,
    StatementIdentification,
    WorkflowCheckpoint,
)


class WorkbenchError(Exception):
    """Stable error raised by the read-only workbench boundary."""

    def __init__(self, code: str, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class WorkbenchSnapshot:
    """Owned persisted entities required to render one complete workspace."""

    run: AnalysisRun
    sources: list[SourceDocument]
    statements: list[StatementIdentification]
    facts: list[FinancialFact]
    metrics: list[CalculatedMetric]
    claims: list[Claim]
    risks: list[RiskFinding]
    reports: list[Report]
    evaluations: list[Evaluation]
    gate_decisions: list[GoalGateDecision]
    checkpoints: list[WorkflowCheckpoint]


def list_owned_runs(session: Session, user_id: str, *, limit: int = 50) -> list[AnalysisRun]:
    """Return only the caller's runs, newest first."""

    return list(
        session.scalars(
            select(AnalysisRun)
            .where(AnalysisRun.user_id == user_id)
            .order_by(AnalysisRun.updated_at.desc(), AnalysisRun.run_id.desc())
            .limit(limit)
        )
    )


def get_workbench_snapshot(session: Session, run_id: str, user_id: str) -> WorkbenchSnapshot:
    """Load an owned run and its persisted analysis entities without side effects."""

    run = session.scalar(
        select(AnalysisRun).where(
            AnalysisRun.run_id == run_id,
            AnalysisRun.user_id == user_id,
        )
    )
    if run is None:
        raise WorkbenchError("run_not_found", "Analysis run was not found.")

    sources = list(
        session.scalars(
            select(SourceDocument)
            .where(SourceDocument.run_id == run_id)
            .order_by(SourceDocument.ingested_at, SourceDocument.source_id)
        )
    )
    source_ids = [source.source_id for source in sources]
    statements = (
        list(
            session.scalars(
                select(StatementIdentification)
                .where(StatementIdentification.source_id.in_(source_ids))
                .order_by(
                    StatementIdentification.source_id,
                    StatementIdentification.statement_type,
                )
            )
        )
        if source_ids
        else []
    )
    return WorkbenchSnapshot(
        run=run,
        sources=sources,
        statements=statements,
        facts=list(
            session.scalars(
                select(FinancialFact)
                .where(FinancialFact.run_id == run_id)
                .order_by(
                    FinancialFact.statement_type,
                    FinancialFact.concept,
                    FinancialFact.created_at,
                )
            )
        ),
        metrics=list(
            session.scalars(
                select(CalculatedMetric)
                .where(CalculatedMetric.run_id == run_id)
                .order_by(CalculatedMetric.metric_code)
            )
        ),
        claims=list(
            session.scalars(
                select(Claim)
                .where(Claim.run_id == run_id)
                .order_by(Claim.created_at, Claim.claim_id)
            )
        ),
        risks=list(
            session.scalars(
                select(RiskFinding)
                .where(RiskFinding.run_id == run_id)
                .order_by(RiskFinding.created_at, RiskFinding.risk_id)
            )
        ),
        reports=list(
            session.scalars(
                select(Report).where(Report.run_id == run_id).order_by(Report.version.desc())
            )
        ),
        evaluations=list(
            session.scalars(
                select(Evaluation)
                .where(Evaluation.run_id == run_id)
                .order_by(Evaluation.created_at.desc(), Evaluation.evaluation_id.desc())
            )
        ),
        gate_decisions=list(
            session.scalars(
                select(GoalGateDecision)
                .where(GoalGateDecision.run_id == run_id)
                .order_by(GoalGateDecision.created_at.desc(), GoalGateDecision.gate_id.desc())
            )
        ),
        checkpoints=list(
            session.scalars(
                select(WorkflowCheckpoint)
                .where(WorkflowCheckpoint.run_id == run_id)
                .order_by(WorkflowCheckpoint.state_version.desc())
            )
        ),
    )
