"""Independent, deterministic evaluation of persisted candidate reports."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import false, select
from sqlalchemy.orm import Session

from citefin.db.models import (
    AnalysisRun,
    AuditEvent,
    CalculatedMetric,
    Claim,
    Evaluation,
    Evidence,
    FinancialFact,
    Report,
    RiskFinding,
)
from citefin.ids import new_prefixed_id

EVALUATOR_VERSION = "deterministic-evaluator-v1"
REPORT_SCHEMA_VERSION = "financial-report-v1"

_EXPECTED_REPORT_SECTIONS = {
    "schema_version",
    "run",
    "facts",
    "calculations",
    "inferences",
    "risks",
    "limitations",
    "evidence",
}
_FORBIDDEN_WORDING = ("买入", "卖出", "目标价", "收益保证", "保证收益", "无风险")


class EvaluationError(Exception):
    """Stable error raised at the independent evaluation boundary."""

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class EvaluationResult:
    """Persisted evaluation and whether the request replayed it."""

    evaluation: Evaluation
    idempotent_replay: bool


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()


def _owned_run(session: Session, run_id: str, user_id: str) -> AnalysisRun:
    run = session.scalar(
        select(AnalysisRun).where(AnalysisRun.run_id == run_id, AnalysisRun.user_id == user_id)
    )
    if run is None:
        raise EvaluationError("run_not_found", "Analysis run was not found.", 404)
    return run


def _check(
    code: str,
    passed: bool,
    message: str,
    *,
    evidence: Iterable[str] = (),
    node_hint: str,
    repair_instruction: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "result": "passed" if passed else "failed",
        "severity": "info" if passed else "blocking",
        "message": message,
        "evidence": sorted(set(evidence)),
        "node_hint": None if passed else node_hint,
        "repair_instruction": None if passed else repair_instruction,
    }


def _claim_ids_in_content(content: dict[str, Any]) -> set[str]:
    claim_ids: set[str] = set()
    calculations = content.get("calculations")
    if isinstance(calculations, dict):
        calculation_claims = calculations.get("claims", [])
        if isinstance(calculation_claims, list):
            claim_ids.update(
                item["claim_id"]
                for item in calculation_claims
                if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
            )
    for key in ("inferences",):
        items = content.get(key, [])
        if isinstance(items, list):
            claim_ids.update(
                item["claim_id"]
                for item in items
                if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
            )
    limitations = content.get("limitations")
    if isinstance(limitations, dict):
        limitation_claims = limitations.get("claims", [])
        if isinstance(limitation_claims, list):
            claim_ids.update(
                item["claim_id"]
                for item in limitation_claims
                if isinstance(item, dict) and isinstance(item.get("claim_id"), str)
            )
    return claim_ids


def _input_snapshot(
    report: Report,
    content: dict[str, Any],
    facts: list[FinancialFact],
    metrics: list[CalculatedMetric],
    claims: list[Claim],
    evidence: list[Evidence],
    risks: list[RiskFinding],
    audit_events: list[AuditEvent],
) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "report_id": report.report_id,
        "report_version": report.version,
        "report_schema_version": report.schema_version,
        "report_content_sha256": _canonical_digest(content),
        "entity_ids": {
            "fact_ids": sorted(fact.fact_id for fact in facts),
            "metric_ids": sorted(metric.metric_id for metric in metrics),
            "claim_ids": sorted(claim.claim_id for claim in claims),
            "evidence_ids": sorted(item.evidence_id for item in evidence),
            "risk_ids": sorted(risk.risk_id for risk in risks),
            "audit_event_ids": sorted(event.event_id for event in audit_events),
        },
        "entity_counts": {
            "facts": len(facts),
            "metrics": len(metrics),
            "claims": len(claims),
            "evidence": len(evidence),
            "risks": len(risks),
            "audit_events": len(audit_events),
        },
    }


def _evaluate_checks(
    report: Report,
    content: dict[str, Any],
    facts: list[FinancialFact],
    metrics: list[CalculatedMetric],
    claims: list[Claim],
    evidence: list[Evidence],
    risks: list[RiskFinding],
    audit_events: list[AuditEvent],
) -> list[dict[str, Any]]:
    fact_ids = {fact.fact_id for fact in facts}
    metric_ids = {metric.metric_id for metric in metrics}
    claim_map = {claim.claim_id: claim for claim in claims}
    evidence_map = {item.evidence_id: item for item in evidence}
    risk_ids = {risk.risk_id for risk in risks}
    report_claim_ids = set(report.claim_ids)
    content_evidence = content.get("evidence")
    content_evidence_map = content_evidence if isinstance(content_evidence, dict) else {}

    schema_ok = (
        report.schema_version == REPORT_SCHEMA_VERSION
        and content.get("schema_version") == REPORT_SCHEMA_VERSION
        and set(content) == _EXPECTED_REPORT_SECTIONS
        and content.get("run", {}).get("run_id") == report.run_id
    )
    checks = [
        _check(
            "report_schema",
            schema_ok,
            "Report schema and run identity are valid."
            if schema_ok
            else "Report schema, sections, or run identity is invalid.",
            evidence=[report.report_id],
            node_hint="write_report",
            repair_instruction=(
                "Rebuild the candidate report with financial-report-v1 sections and "
                "the owned run identity."
            ),
        )
    ]

    expected_claim_ids = {claim.claim_id for claim in claims if claim.status == "supported"}
    major_claims = {
        claim.claim_id
        for claim in claims
        if claim.materiality == "major" and claim.status == "supported"
    }
    missing_claims = expected_claim_ids - report_claim_ids
    missing_major_evidence = {
        claim.claim_id
        for claim in claims
        if claim.claim_id in major_claims
        and (
            not claim.evidence_ids
            or any(evidence_id not in content_evidence_map for evidence_id in claim.evidence_ids)
        )
    }
    claim_evidence_ok = not missing_claims and not missing_major_evidence
    checks.append(
        _check(
            "claim_evidence_coverage",
            claim_evidence_ok,
            "Supported claims and major-claim evidence are covered."
            if claim_evidence_ok
            else (
                f"Missing claims: {sorted(missing_claims)}; missing major evidence: "
                f"{sorted(missing_major_evidence)}."
            ),
            evidence=[*sorted(missing_claims), *sorted(missing_major_evidence)],
            node_hint="build_evidence_map",
            repair_instruction=(
                "Add or repair Evidence for every supported major Claim, then rebuild "
                "the report candidate."
            ),
        )
    )

    invalid_evidence = []
    rendered_evidence_ids = set(content_evidence_map)
    relevant_evidence_ids = {
        item.evidence_id for item in evidence if item.claim_id in report_claim_ids
    }
    invalid_evidence.extend(sorted(rendered_evidence_ids - set(evidence_map)))
    invalid_evidence.extend(sorted(relevant_evidence_ids - rendered_evidence_ids))
    for item in evidence:
        if item.claim_id not in report_claim_ids:
            continue
        target_ids = [item.source_id, item.fact_id, item.metric_id, item.rule_id]
        if sum(target is not None for target in target_ids) != 1:
            invalid_evidence.append(item.evidence_id)
            continue
        if item.fact_id is not None and item.fact_id not in fact_ids:
            invalid_evidence.append(item.evidence_id)
        if item.metric_id is not None and item.metric_id not in metric_ids:
            invalid_evidence.append(item.evidence_id)
        rendered = content_evidence_map.get(item.evidence_id)
        if not isinstance(rendered, dict) or rendered.get("claim_id") != item.claim_id:
            invalid_evidence.append(item.evidence_id)
    evidence_ok = not invalid_evidence
    checks.append(
        _check(
            "evidence_referential_integrity",
            evidence_ok,
            "Evidence targets and rendered claim links are valid."
            if evidence_ok
            else f"Invalid evidence references: {sorted(set(invalid_evidence))}.",
            evidence=invalid_evidence,
            node_hint="build_evidence_map",
            repair_instruction=(
                "Repair Evidence target IDs and claim mappings before regenerating the report."
            ),
        )
    )

    rendered_metrics = content.get("calculations", {}).get("metrics", [])
    rendered_metric_map = {
        item.get("metric_id"): item
        for item in rendered_metrics
        if isinstance(item, dict) and isinstance(item.get("metric_id"), str)
    }
    missing_metrics = metric_ids - set(rendered_metric_map)
    invalid_metrics = [
        metric.metric_id
        for metric in metrics
        if metric.metric_id in rendered_metric_map
        and (
            rendered_metric_map[metric.metric_id].get("status") != metric.status
            or not isinstance(rendered_metric_map[metric.metric_id].get("input_snapshot"), dict)
            or rendered_metric_map[metric.metric_id].get("calculator_version")
            != metric.calculator_version
        )
    ]
    metric_ok = not missing_metrics and not invalid_metrics
    checks.append(
        _check(
            "metric_lineage",
            metric_ok,
            "All persisted metrics have status and calculation lineage in the report."
            if metric_ok
            else (
                f"Missing metrics: {sorted(missing_metrics)}; invalid metrics: "
                f"{sorted(invalid_metrics)}."
            ),
            evidence=[*sorted(missing_metrics), *invalid_metrics],
            node_hint="calculate_metrics",
            repair_instruction=(
                "Recalculate or restore the metric input snapshot and calculator version, "
                "then rebuild the report."
            ),
        )
    )

    rendered_risks = content.get("risks", [])
    rendered_risk_map = {
        item.get("risk_id"): item
        for item in rendered_risks
        if isinstance(item, dict) and isinstance(item.get("risk_id"), str)
    }
    risk_problems = []
    for risk in risks:
        rendered = rendered_risk_map.get(risk.risk_id)
        if rendered is None or set(risk.claim_ids) - report_claim_ids:
            risk_problems.append(risk.risk_id)
            continue
        if not set(risk.claim_ids).issubset(
            {claim_id for claim_id in report_claim_ids if claim_map.get(claim_id) is not None}
        ):
            risk_problems.append(risk.risk_id)
    risk_ok = not risk_problems and risk_ids == set(rendered_risk_map)
    checks.append(
        _check(
            "risk_traceability",
            risk_ok,
            "Persisted risks are represented with report claim references."
            if risk_ok
            else f"Risk traceability problems: {sorted(set(risk_problems))}.",
            evidence=[*sorted(set(risk_problems)), *sorted(risk_ids - set(rendered_risk_map))],
            node_hint="detect_risks",
            repair_instruction=(
                "Restore each risk's Claim and Evidence links before regenerating the report."
            ),
        )
    )

    report_text = json.dumps(content, ensure_ascii=False, sort_keys=True)
    wording_violations = [phrase for phrase in _FORBIDDEN_WORDING if phrase in report_text]
    wording_ok = not wording_violations
    checks.append(
        _check(
            "compliance_wording",
            wording_ok,
            "No forbidden investment instruction or guarantee wording is present."
            if wording_ok
            else f"Forbidden wording detected: {wording_violations}.",
            evidence=[report.report_id],
            node_hint="write_report",
            repair_instruction=(
                "Remove investment instructions, guarantees, and target-price wording; "
                "retain evidence-backed risk language only."
            ),
        )
    )

    audit_ok = any(
        event.event_type == "report_candidate_generated"
        and event.payload.get("report_id") == report.report_id
        for event in audit_events
    )
    checks.append(
        _check(
            "audit_completeness",
            audit_ok,
            "Report generation has an auditable lifecycle event."
            if audit_ok
            else "The report generation audit event is missing.",
            evidence=[report.report_id],
            node_hint="write_report",
            repair_instruction=(
                "Restore the append-only report generation audit event before evaluating "
                "completion."
            ),
        )
    )
    return checks


def evaluate_and_persist_report(
    session: Session, run_id: str, user_id: str, report_id: str
) -> EvaluationResult:
    """Evaluate one owned report without invoking any report-generation service."""

    _owned_run(session, run_id, user_id)
    report = session.scalar(
        select(Report).where(Report.report_id == report_id, Report.run_id == run_id)
    )
    if report is None:
        raise EvaluationError(
            "report_not_found", "Report was not found for this analysis run.", 404
        )
    existing = session.scalar(
        select(Evaluation).where(
            Evaluation.report_id == report_id,
            Evaluation.evaluator_version == EVALUATOR_VERSION,
        )
    )
    if existing is not None:
        return EvaluationResult(existing, True)

    facts = list(session.scalars(select(FinancialFact).where(FinancialFact.run_id == run_id)))
    metrics = list(
        session.scalars(select(CalculatedMetric).where(CalculatedMetric.run_id == run_id))
    )
    claims = list(session.scalars(select(Claim).where(Claim.run_id == run_id)))
    claim_ids = [claim.claim_id for claim in claims]
    evidence = list(
        session.scalars(
            select(Evidence).where(Evidence.claim_id.in_(claim_ids))
            if claim_ids
            else select(Evidence).where(false())
        )
    )
    risks = list(session.scalars(select(RiskFinding).where(RiskFinding.run_id == run_id)))
    audit_events = list(session.scalars(select(AuditEvent).where(AuditEvent.run_id == run_id)))
    content = report.content
    snapshot = _input_snapshot(
        report, content, facts, metrics, claims, evidence, risks, audit_events
    )
    try:
        checks = _evaluate_checks(
            report, content, facts, metrics, claims, evidence, risks, audit_events
        )
        blocking = [check for check in checks if check["result"] == "failed"]
        status = "failed" if blocking else "passed"
        node_hint = blocking[0]["node_hint"] if blocking else None
        repair_instruction = (
            "；".join(
                check["repair_instruction"] for check in blocking if check["repair_instruction"]
            )
            or None
        )
        blocking_reasons = [
            {
                "code": check["code"],
                "message": check["message"],
                "evidence": check["evidence"],
                "node_hint": check["node_hint"],
                "repair_instruction": check["repair_instruction"],
            }
            for check in blocking
        ]
    except Exception as error:
        checks = [
            {
                "code": "evaluator_error",
                "result": "failed",
                "severity": "blocking",
                "message": str(error),
                "evidence": [report.report_id],
                "node_hint": "goal_evaluator",
                "repair_instruction": (
                    "Inspect the persisted evaluation inputs and rerun the independent evaluator."
                ),
            }
        ]
        blocking_reasons = checks.copy()
        status = "error"
        node_hint = "goal_evaluator"
        repair_instruction = (
            "Inspect the persisted evaluation inputs and rerun the independent evaluator."
        )

    now = datetime.now(UTC)
    evaluation = Evaluation(
        evaluation_id=new_prefixed_id("eval"),
        run_id=run_id,
        report_id=report_id,
        evaluator_version=EVALUATOR_VERSION,
        status=status,
        checks=checks,
        blocking_reasons=blocking_reasons,
        input_snapshot=snapshot,
        node_hint=node_hint,
        repair_instruction=repair_instruction,
        created_at=now,
    )
    event = AuditEvent(
        event_id=new_prefixed_id("event"),
        run_id=run_id,
        trace_id=new_prefixed_id("trace"),
        node="goal_evaluator",
        event_type="evaluation_completed",
        status=status,
        payload={
            "evaluation_id": evaluation.evaluation_id,
            "report_id": report_id,
            "evaluator_version": EVALUATOR_VERSION,
            "evaluation_status": status,
            "check_count": len(checks),
            "blocking_count": len(blocking_reasons),
        },
        created_at=now,
    )
    session.add_all([evaluation, event])
    session.commit()
    return EvaluationResult(evaluation, False)
