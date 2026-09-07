"""Claim and evidence persistence with source-lineage validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    CalculatedMetric,
    Claim,
    DocumentPage,
    Evidence,
    FinancialFact,
    SourceDocument,
)
from citefin.ids import new_prefixed_id

EvidenceType = Literal["source_locator", "fact", "metric", "rule"]
Supports = Literal["supports", "contradicts", "qualifies"]


@dataclass(frozen=True)
class EvidenceError(Exception):
    """Stable error raised when a claim or evidence link is invalid."""

    code: str
    message: str
    status_code: int = 422

    def __str__(self) -> str:
        return self.message


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise EvidenceError("run_not_found", "Analysis run was not found.", 404)
    return run


def create_claim(
    session: Session,
    run_id: str,
    user_id: str,
    claim_type: str,
    text: str,
    materiality: str,
    created_by: str,
) -> Claim:
    """Create a draft atomic claim without inventing supporting evidence."""

    _owned_run(session, run_id, user_id)
    now = datetime.now(UTC)
    claim = Claim(
        claim_id=new_prefixed_id("claim"),
        run_id=run_id,
        claim_type=claim_type,
        text=text,
        materiality=materiality,
        status="draft",
        evidence_ids=[],
        created_by=created_by,
        created_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="build_evidence_map",
        event_type="claim_created",
        status="success",
        payload={"claim_id": claim.claim_id, "materiality": materiality},
        created_at=now,
    )
    session.add_all([claim, event])
    session.commit()
    return claim


def _validate_target(
    session: Session,
    run_id: str,
    evidence_type: EvidenceType,
    source_id: str | None,
    page_number: int | None,
    fact_id: str | None,
    metric_id: str | None,
    rule_id: str | None,
) -> None:
    targets = [
        source_id is not None,
        fact_id is not None,
        metric_id is not None,
        rule_id is not None,
    ]
    if sum(targets) != 1:
        raise EvidenceError(
            "invalid_evidence_target", "Evidence must point to exactly one primary target."
        )
    expected_target = {
        "source_locator": source_id is not None,
        "fact": fact_id is not None,
        "metric": metric_id is not None,
        "rule": rule_id is not None,
    }[evidence_type]
    if not expected_target:
        raise EvidenceError(
            "evidence_type_target_mismatch", "Evidence type does not match its primary target."
        )

    if evidence_type == "source_locator":
        if page_number is None or page_number < 1:
            raise EvidenceError(
                "invalid_source_locator", "Source locator evidence requires a positive page number."
            )
        source = session.scalar(
            select(SourceDocument).where(
                SourceDocument.source_id == source_id, SourceDocument.run_id == run_id
            )
        )
        page = session.get(DocumentPage, (source_id, page_number))
        if source is None or page is None:
            raise EvidenceError(
                "source_locator_not_found", "Source document page is not available for this run."
            )
    elif evidence_type == "fact":
        fact = session.scalar(
            select(FinancialFact).where(
                FinancialFact.fact_id == fact_id, FinancialFact.run_id == run_id
            )
        )
        if fact is None:
            raise EvidenceError("fact_not_found", "Financial fact is not available for this run.")
    elif evidence_type == "metric":
        metric = session.scalar(
            select(CalculatedMetric).where(
                CalculatedMetric.metric_id == metric_id, CalculatedMetric.run_id == run_id
            )
        )
        if metric is None:
            raise EvidenceError(
                "metric_not_found", "Calculated metric is not available for this run."
            )


def add_evidence(
    session: Session,
    run_id: str,
    user_id: str,
    claim_id: str,
    evidence_type: EvidenceType,
    supports: Supports,
    source_id: str | None = None,
    page_number: int | None = None,
    locator: dict[str, Any] | None = None,
    fact_id: str | None = None,
    metric_id: str | None = None,
    rule_id: str | None = None,
    excerpt: str | None = None,
) -> Evidence:
    """Attach exactly one validated evidence target to an owned claim."""

    _owned_run(session, run_id, user_id)
    claim = session.scalar(select(Claim).where(Claim.claim_id == claim_id, Claim.run_id == run_id))
    if claim is None:
        raise EvidenceError("claim_not_found", "Claim was not found for this run.", 404)
    _validate_target(
        session,
        run_id,
        evidence_type,
        source_id,
        page_number,
        fact_id,
        metric_id,
        rule_id,
    )
    now = datetime.now(UTC)
    evidence = Evidence(
        evidence_id=new_prefixed_id("evidence"),
        claim_id=claim_id,
        evidence_type=evidence_type,
        source_id=source_id,
        page_number=page_number,
        locator=locator,
        fact_id=fact_id,
        metric_id=metric_id,
        rule_id=rule_id,
        excerpt=excerpt,
        supports=supports,
        created_at=now,
    )
    claim.evidence_ids = [*claim.evidence_ids, evidence.evidence_id]
    if supports == "supports":
        claim.status = "supported"
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="build_evidence_map",
        event_type="evidence_attached",
        status="success",
        payload={"claim_id": claim_id, "evidence_id": evidence.evidence_id},
        created_at=now,
    )
    session.add_all([evidence, event])
    session.commit()
    return evidence
