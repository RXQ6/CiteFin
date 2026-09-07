"""Deterministic F011 report assembly from persisted facts, claims, and evidence."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    CalculatedMetric,
    Claim,
    Evidence,
    FinancialFact,
    Report,
    RiskFinding,
    SourceDocument,
)
from citefin.ids import new_prefixed_id

REPORT_SCHEMA_VERSION = "financial-report-v1"
REPORT_GENERATOR_VERSION = "deterministic-report-v1"


class ReportGenerationError(Exception):
    """Stable error raised at the structured report boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ReportGenerationResult:
    """Persisted report and whether the request replayed an existing version."""

    report: Report
    idempotent_replay: bool


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _datetime_text(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.isoformat()


def _claim_item(claim: Claim) -> dict[str, Any]:
    return {
        "claim_id": claim.claim_id,
        "claim_type": claim.claim_type,
        "text": claim.text,
        "materiality": claim.materiality,
        "status": claim.status,
        "evidence_ids": list(claim.evidence_ids),
        "created_by": claim.created_by,
    }


def _fact_item(fact: FinancialFact) -> dict[str, Any]:
    return {
        "fact_id": fact.fact_id,
        "statement_type": fact.statement_type,
        "concept": fact.concept,
        "label_raw": fact.label_raw,
        "period_start": fact.period_start.isoformat() if fact.period_start else None,
        "period_end": fact.period_end.isoformat(),
        "period_type": fact.period_type,
        "scope": fact.scope,
        "currency": fact.currency,
        "display_unit": fact.display_unit,
        "raw_value": _decimal_text(fact.raw_value),
        "normalized_value": _decimal_text(fact.normalized_value),
        "validation_status": fact.validation_status,
        "source": {
            "source_id": fact.source_id,
            "page_number": fact.page_number,
            "section": fact.section,
            "table_id": fact.table_id,
            "row_label": fact.row_label,
            "column_label": fact.column_label,
            "bbox": fact.bbox,
        },
    }


def _metric_item(metric: CalculatedMetric) -> dict[str, Any]:
    return {
        "metric_id": metric.metric_id,
        "metric_code": metric.metric_code,
        "definition_version": metric.definition_version,
        "period_end": metric.period_end.isoformat(),
        "input_fact_ids": list(metric.input_fact_ids),
        "input_snapshot": metric.input_snapshot,
        "value": _decimal_text(metric.value),
        "unit": metric.unit,
        "status": metric.status,
        "reason": metric.reason,
        "calculator_version": metric.calculator_version,
    }


def _source_ref(fact: FinancialFact) -> dict[str, Any]:
    return {
        "source_id": fact.source_id,
        "page_number": fact.page_number,
        "section": fact.section,
        "table_id": fact.table_id,
        "row_label": fact.row_label,
        "column_label": fact.column_label,
        "bbox": fact.bbox,
    }


def _evidence_item(
    evidence: Evidence,
    facts: dict[str, FinancialFact],
    metrics: dict[str, CalculatedMetric],
    sources: dict[str, SourceDocument],
) -> dict[str, Any]:
    targets = [
        ("source_locator", evidence.source_id),
        ("fact", evidence.fact_id),
        ("metric", evidence.metric_id),
        ("rule", evidence.rule_id),
    ]
    target_type, target_id = next(((kind, value) for kind, value in targets if value), (None, None))
    if target_type is None or target_id is None:
        raise ReportGenerationError(
            "invalid_evidence_target", f"Evidence {evidence.evidence_id} has no primary target."
        )
    source_refs: list[dict[str, Any]] = []
    if target_type == "source_locator":
        if target_id not in sources or evidence.page_number is None:
            raise ReportGenerationError(
                "missing_source_evidence", f"Evidence {evidence.evidence_id} has no source."
            )
        source_refs.append(
            {
                "source_id": target_id,
                "page_number": evidence.page_number,
                "locator": evidence.locator,
            }
        )
    elif target_type == "fact":
        fact = facts.get(target_id)
        if fact is None:
            raise ReportGenerationError(
                "missing_fact_evidence",
                f"Evidence {evidence.evidence_id} references a missing fact.",
            )
        source_refs.append(_source_ref(fact))
    elif target_type == "metric":
        metric = metrics.get(target_id)
        if metric is None:
            raise ReportGenerationError(
                "missing_metric_evidence",
                f"Evidence {evidence.evidence_id} references a missing metric.",
            )
        source_refs.extend(
            _source_ref(facts[fact_id]) for fact_id in metric.input_fact_ids if fact_id in facts
        )
    return {
        "evidence_id": evidence.evidence_id,
        "claim_id": evidence.claim_id,
        "evidence_type": evidence.evidence_type,
        "supports": evidence.supports,
        "target": {"type": target_type, "id": target_id},
        "source_refs": source_refs,
        "excerpt": evidence.excerpt,
    }


def build_report_content(
    run: AnalysisRun,
    facts: Iterable[FinancialFact],
    metrics: Iterable[CalculatedMetric],
    claims: Iterable[Claim],
    evidence: Iterable[Evidence],
    risk_findings: Iterable[RiskFinding],
    sources: Iterable[SourceDocument],
) -> tuple[dict[str, Any], list[str]]:
    """Build a versioned report without changing any source entity."""

    fact_items = sorted(facts, key=lambda item: (item.period_end, item.fact_id))
    metric_items = sorted(metrics, key=lambda item: item.metric_code)
    source_map = {source.source_id: source for source in sources}
    fact_map = {fact.fact_id: fact for fact in fact_items}
    metric_map = {metric.metric_id: metric for metric in metric_items}
    all_claims = sorted(claims, key=lambda item: item.claim_id)
    unsupported_major = [
        claim
        for claim in all_claims
        if claim.status != "supported" and claim.materiality == "major"
    ]
    if unsupported_major:
        raise ReportGenerationError(
            "unsupported_claim",
            "Major claims must be supported before a report candidate can be generated.",
        )
    supported_claims = [claim for claim in all_claims if claim.status == "supported"]
    if not supported_claims:
        raise ReportGenerationError(
            "no_supported_claims", "No supported claims are available for report generation."
        )
    evidence_by_claim: dict[str, list[Evidence]] = defaultdict(list)
    for item in evidence:
        evidence_by_claim[item.claim_id].append(item)
    for claim in supported_claims:
        if claim.materiality == "major" and not evidence_by_claim.get(claim.claim_id):
            raise ReportGenerationError(
                "missing_evidence", f"Major claim {claim.claim_id} has no evidence."
            )
    evidence_map = {
        item.evidence_id: _evidence_item(item, fact_map, metric_map, source_map)
        for item in sorted(evidence, key=lambda item: item.evidence_id)
    }
    claims_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for claim in supported_claims:
        claims_by_type[claim.claim_type].append(_claim_item(claim))
    claim_map = {claim.claim_id: claim for claim in supported_claims}
    risks: list[dict[str, Any]] = []
    risk_limitations: list[dict[str, Any]] = []
    for finding in sorted(risk_findings, key=lambda item: item.risk_code):
        risk_claims = [
            claim_map[claim_id] for claim_id in finding.claim_ids if claim_id in claim_map
        ]
        if len(risk_claims) != len(finding.claim_ids):
            raise ReportGenerationError(
                "missing_risk_claim", f"Risk {finding.risk_id} references a missing claim."
            )
        risk_evidence_ids = [
            evidence_id for claim in risk_claims for evidence_id in claim.evidence_ids
        ]
        risks.append(
            {
                "risk_id": finding.risk_id,
                "risk_code": finding.risk_code,
                "period_end": finding.period_end.isoformat(),
                "category": finding.category,
                "severity": finding.severity,
                "title": finding.title,
                "description": finding.description,
                "status": finding.status,
                "confidence": _decimal_text(finding.confidence),
                "limitations": list(finding.limitations),
                "claim_ids": list(finding.claim_ids),
                "evidence_ids": risk_evidence_ids,
            }
        )
        risk_limitations.extend(
            {"risk_id": finding.risk_id, "text": limitation} for limitation in finding.limitations
        )
    currencies = sorted({fact.currency for fact in fact_items})
    display_units = sorted({fact.display_unit for fact in fact_items})
    scopes = sorted({fact.scope for fact in fact_items})
    claim_ids = [claim.claim_id for claim in supported_claims]
    content = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run": {
            "run_id": run.run_id,
            "company_name": run.company_name,
            "security_code": run.security_code,
            "report_period_end": run.report_period_end.isoformat(),
            "as_of": _datetime_text(run.as_of),
            "currency": currencies[0] if len(currencies) == 1 else None,
            "display_unit": display_units[0] if len(display_units) == 1 else None,
            "scope": scopes[0] if len(scopes) == 1 else None,
        },
        "facts": [_fact_item(fact) for fact in fact_items],
        "calculations": {
            "metrics": [_metric_item(metric) for metric in metric_items],
            "claims": claims_by_type.get("calculation", []),
        },
        "inferences": claims_by_type.get("inference", []),
        "risks": risks,
        "limitations": {
            "claims": claims_by_type.get("limitation", []),
            "risk_limitations": risk_limitations,
        },
        "evidence": evidence_map,
    }
    return content, claim_ids


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise ReportGenerationError("run_not_found", "Analysis run was not found.", 404)
    return run


def generate_and_persist_report(
    session: Session, run_id: str, user_id: str, period_end: date
) -> ReportGenerationResult:
    """Assemble one idempotent candidate report from durable, user-owned entities."""

    run = _owned_run(session, run_id, user_id)
    if run.report_period_end != period_end:
        raise ReportGenerationError(
            "report_period_mismatch", "Report period does not match the analysis run."
        )
    existing = session.scalar(
        select(Report)
        .where(Report.run_id == run_id, Report.generated_by == REPORT_GENERATOR_VERSION)
        .order_by(Report.version.desc())
    )
    if existing is not None:
        return ReportGenerationResult(existing, True)
    facts = list(session.scalars(select(FinancialFact).where(FinancialFact.run_id == run_id)))
    metrics = list(
        session.scalars(
            select(CalculatedMetric).where(
                CalculatedMetric.run_id == run_id,
                CalculatedMetric.period_end == period_end,
            )
        )
    )
    claims = list(session.scalars(select(Claim).where(Claim.run_id == run_id)))
    claim_ids = [claim.claim_id for claim in claims]
    evidence_query = (
        select(Evidence).where(Evidence.claim_id.in_(claim_ids))
        if claim_ids
        else select(Evidence).where(false())
    )
    evidence = list(session.scalars(evidence_query))
    risk_findings = list(
        session.scalars(
            select(RiskFinding).where(
                RiskFinding.run_id == run_id, RiskFinding.period_end == period_end
            )
        )
    )
    sources = list(session.scalars(select(SourceDocument).where(SourceDocument.run_id == run_id)))
    content, report_claim_ids = build_report_content(
        run, facts, metrics, claims, evidence, risk_findings, sources
    )
    latest_version = (
        session.scalar(select(func.max(Report.version)).where(Report.run_id == run_id)) or 0
    )
    now = datetime.now(UTC)
    report = Report(
        report_id=new_prefixed_id("report"),
        run_id=run_id,
        version=latest_version + 1,
        status="candidate",
        schema_version=REPORT_SCHEMA_VERSION,
        content=content,
        claim_ids=report_claim_ids,
        generated_by=REPORT_GENERATOR_VERSION,
        created_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="write_report",
        event_type="report_candidate_generated",
        status="success",
        payload={
            "report_id": report.report_id,
            "report_version": report.version,
            "schema_version": REPORT_SCHEMA_VERSION,
            "claim_count": len(report_claim_ids),
            "risk_count": len(risk_findings),
        },
        created_at=now,
    )
    session.add_all([report, event])
    session.commit()
    return ReportGenerationResult(report, False)
