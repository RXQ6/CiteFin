"""Deterministic validation and scoring for the F004 blind-review package."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

SUBMISSION_SCHEMA_VERSION = "f004-review-submission-v1"
RESULT_SCHEMA_VERSION = "f004-review-result-v1"
VALIDATOR_VERSION = "f004-review-validator-v1"
STATEMENT_TYPES = {"balance_sheet", "income_statement", "cashflow_statement"}
REVIEW_STATUSES = {"located", "missing", "ambiguous"}
HUMAN_ID_PATTERN = re.compile(r"human-[a-z0-9][a-z0-9_-]{2,31}\Z")
COMPARISON_FIELDS = (
    "status",
    "title_raw",
    "page_start",
    "page_end",
    "scope",
    "period_end",
    "locator",
    "page_text_sha256",
    "evidence_excerpt",
    "reason_code",
)
REVIEW_COLUMNS = [
    "schema_version",
    "sample_id",
    "security_code",
    "company_name",
    "report_year",
    "statement_type",
    "reviewer_id",
    "status",
    "title_raw",
    "page_start",
    "page_end",
    "scope",
    "period_end",
    "locator",
    "page_text_sha256",
    "evidence_excerpt",
    "reason_code",
    "reviewed_at",
]
ADJUDICATION_COLUMNS = [
    "schema_version",
    "sample_id",
    "statement_type",
    "adjudicator_id",
    "adjudication_status",
    "final_status",
    "final_title_raw",
    "final_page_start",
    "final_page_end",
    "final_scope",
    "final_period_end",
    "final_locator",
    "final_page_text_sha256",
    "final_evidence_excerpt",
    "final_reason_code",
    "adjudication_reason",
    "adjudicated_at",
]


class ReviewPackageError(ValueError):
    """A stable validation failure for an untrustworthy review package."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_key(row: dict[str, str]) -> tuple[str, str]:
    return row.get("sample_id", ""), row.get("statement_type", "")


def validate_corpus(
    manifest: dict[str, Any], queue: list[dict[str, str]], data_root: Path
) -> dict[tuple[str, str], dict[str, str]]:
    """Validate the immutable ten-report corpus and its thirty target identities."""

    reports = manifest.get("reports")
    if not isinstance(reports, list) or len(reports) != 10:
        raise ReviewPackageError("invalid_corpus", "Corpus must contain exactly 10 reports.")
    if len(queue) != 30:
        raise ReviewPackageError("invalid_review_queue", "Review queue must contain 30 rows.")
    targets = {_target_key(row): row for row in queue}
    if len(targets) != 30 or any(key[1] not in STATEMENT_TYPES for key in targets):
        raise ReviewPackageError(
            "invalid_review_queue", "Review queue must contain 30 unique supported targets."
        )

    reports_by_code: dict[str, dict[str, Any]] = {}
    for report in reports:
        if not isinstance(report, dict):
            raise ReviewPackageError("invalid_corpus", "Every report entry must be an object.")
        code = str(report.get("security_code", ""))
        path = data_root / str(report.get("file", ""))
        if code in reports_by_code or not path.is_file():
            raise ReviewPackageError("invalid_corpus", f"Missing or duplicate report: {code}.")
        if path.stat().st_size != report.get("bytes") or sha256_file(path) != report.get("sha256"):
            raise ReviewPackageError("corpus_hash_mismatch", f"Corpus hash mismatch: {path.name}.")
        if len(PdfReader(str(path)).pages) != report.get("pages"):
            raise ReviewPackageError("corpus_page_mismatch", f"Corpus page mismatch: {path.name}.")
        reports_by_code[code] = report

    for key, target in targets.items():
        code = target.get("security_code", "")
        report = reports_by_code.get(code)
        if report is None:
            raise ReviewPackageError("invalid_review_queue", f"Unknown report target: {key}.")
        expected_year = str(report.get("report_year", ""))
        expected_sample = f"{code}-{expected_year}"
        if (
            key[0] != expected_sample
            or target.get("report_year", "") != expected_year
            or target.get("company_name", "") != str(report.get("company_name", ""))
        ):
            raise ReviewPackageError("invalid_review_queue", f"Target identity mismatch: {key}.")
    return targets


def _all_blank(rows: list[dict[str, str]]) -> bool:
    return bool(rows) and all(not row.get("status", "").strip() for row in rows)


def _validate_human_id(value: str, role: str) -> None:
    if not HUMAN_ID_PATTERN.fullmatch(value):
        raise ReviewPackageError(
            "invalid_reviewer_identity",
            f"{role} must use a non-identifying human-* reviewer code.",
        )


def _parse_page(value: str, field: str, maximum: int) -> int:
    try:
        page = int(value)
    except ValueError as error:
        raise ReviewPackageError("invalid_page", f"{field} must be an integer.") from error
    if not 1 <= page <= maximum:
        raise ReviewPackageError("invalid_page", f"{field} is outside the source PDF.")
    return page


def _validate_timestamp(value: str, field: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ReviewPackageError("invalid_timestamp", f"{field} must be ISO-8601.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReviewPackageError(
            "invalid_timestamp", f"{field} must include an explicit UTC offset."
        )


def _verify_page_hash(
    row: dict[str, str], report: dict[str, Any], data_root: Path, cache: dict[tuple[str, int], str]
) -> None:
    page = int(row["page_start"])
    key = (str(report["file"]), page)
    if key not in cache:
        reader = PdfReader(str(data_root / str(report["file"])))
        text = reader.pages[page - 1].extract_text() or ""
        cache[key] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if row["page_text_sha256"] != cache[key]:
        raise ReviewPackageError(
            "page_hash_mismatch", f"Page text hash mismatch for {_target_key(row)}."
        )


def _validate_submission(
    rows: list[dict[str, str]],
    targets: dict[tuple[str, str], dict[str, str]],
    reports_by_code: dict[str, dict[str, Any]],
    data_root: Path,
    *,
    verify_page_hashes: bool,
) -> tuple[str, dict[tuple[str, str], dict[str, str]]]:
    if len(rows) != len(targets) or {_target_key(row) for row in rows} != set(targets):
        raise ReviewPackageError(
            "invalid_submission_targets", "Submission targets do not match queue."
        )
    if any(set(row) != set(REVIEW_COLUMNS) for row in rows):
        raise ReviewPackageError(
            "invalid_submission_columns", "Submission columns do not match the versioned template."
        )
    if _all_blank(rows):
        return "", {}
    if any(not row.get("status", "").strip() for row in rows):
        raise ReviewPackageError(
            "partial_submission", "A submitted review must complete all targets."
        )

    reviewer_ids = {row.get("reviewer_id", "").strip() for row in rows}
    if len(reviewer_ids) != 1:
        raise ReviewPackageError(
            "mixed_reviewer_identity", "One submission must have one reviewer."
        )
    reviewer_id = reviewer_ids.pop()
    _validate_human_id(reviewer_id, "reviewer")
    page_hash_cache: dict[tuple[str, int], str] = {}
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = _target_key(row)
        target = targets[key]
        for identity in ("schema_version", "security_code", "company_name", "report_year"):
            expected = (
                SUBMISSION_SCHEMA_VERSION if identity == "schema_version" else target[identity]
            )
            if row.get(identity, "") != expected:
                raise ReviewPackageError(
                    "submission_identity_mismatch", f"{identity} mismatch for {key}."
                )
        status = row["status"]
        if status not in REVIEW_STATUSES:
            raise ReviewPackageError("invalid_review_status", f"Invalid status for {key}.")
        _validate_timestamp(row.get("reviewed_at", ""), "reviewed_at")
        report = reports_by_code[row["security_code"]]
        if status == "located":
            required = (
                "title_raw",
                "page_start",
                "page_end",
                "scope",
                "period_end",
                "locator",
                "page_text_sha256",
                "evidence_excerpt",
            )
            if any(not row.get(field, "").strip() for field in required):
                raise ReviewPackageError(
                    "missing_locator_field", f"Located target incomplete: {key}."
                )
            start = _parse_page(row["page_start"], "page_start", int(report["pages"]))
            end = _parse_page(row["page_end"], "page_end", int(report["pages"]))
            if end < start or row["scope"] != "consolidated":
                raise ReviewPackageError(
                    "invalid_locator", f"Invalid consolidated range for {key}."
                )
            if not re.fullmatch(r"[0-9a-f]{64}", row["page_text_sha256"]):
                raise ReviewPackageError("invalid_page_hash", f"Invalid page hash for {key}.")
            if verify_page_hashes:
                _verify_page_hash(row, report, data_root, page_hash_cache)
        elif not row.get("reason_code", "").strip() or not row.get("evidence_excerpt", "").strip():
            raise ReviewPackageError(
                "missing_review_reason",
                f"Missing/ambiguous target needs evidence and reason: {key}.",
            )
        indexed[key] = row
    return reviewer_id, indexed


def _same(a: dict[str, str], b: dict[str, str], field: str) -> bool:
    return a.get(field, "").strip() == b.get(field, "").strip()


def _adjudicated_truth(
    conflicts: list[tuple[str, str]],
    adjudications: list[dict[str, str]],
    reviewer_ids: set[str],
    targets: dict[tuple[str, str], dict[str, str]],
    reports_by_code: dict[str, dict[str, Any]],
    data_root: Path,
    *,
    verify_page_hashes: bool,
) -> dict[tuple[str, str], dict[str, str]]:
    completion_fields = (
        "adjudicator_id",
        "adjudication_status",
        "final_status",
        "final_title_raw",
        "final_page_start",
        "final_page_end",
        "final_scope",
        "final_period_end",
        "final_locator",
        "final_page_text_sha256",
        "final_evidence_excerpt",
        "final_reason_code",
        "adjudication_reason",
        "adjudicated_at",
    )
    indexed = {
        _target_key(row): row
        for row in adjudications
        if any(row.get(field, "").strip() for field in completion_fields)
    }
    if any(set(row) != set(ADJUDICATION_COLUMNS) for row in adjudications):
        raise ReviewPackageError(
            "invalid_adjudication_columns",
            "Adjudication columns do not match the versioned template.",
        )
    if set(indexed) != set(conflicts):
        raise ReviewPackageError(
            "incomplete_adjudication", "Adjudication rows must exactly match review conflicts."
        )
    adjudicator_ids = {row.get("adjudicator_id", "").strip() for row in indexed.values()}
    if len(adjudicator_ids) != 1:
        raise ReviewPackageError("mixed_adjudicator_identity", "Use one adjudicator per package.")
    adjudicator_id = adjudicator_ids.pop()
    _validate_human_id(adjudicator_id, "adjudicator")
    if adjudicator_id in reviewer_ids:
        raise ReviewPackageError("role_conflict", "Reviewers and adjudicator must be distinct.")
    truth: dict[tuple[str, str], dict[str, str]] = {}
    page_hash_cache: dict[tuple[str, int], str] = {}
    for key, row in indexed.items():
        if row.get("schema_version") != SUBMISSION_SCHEMA_VERSION:
            raise ReviewPackageError("adjudication_schema_mismatch", f"Schema mismatch: {key}.")
        if row.get("adjudication_status") != "adjudicated":
            raise ReviewPackageError("incomplete_adjudication", f"Conflict not adjudicated: {key}.")
        if not row.get("adjudication_reason", "").strip():
            raise ReviewPackageError("missing_adjudication_reason", f"Missing reason: {key}.")
        _validate_timestamp(row.get("adjudicated_at", ""), "adjudicated_at")
        truth[key] = {
            "status": row.get("final_status", ""),
            "title_raw": row.get("final_title_raw", ""),
            "page_start": row.get("final_page_start", ""),
            "page_end": row.get("final_page_end", ""),
            "scope": row.get("final_scope", ""),
            "period_end": row.get("final_period_end", ""),
            "locator": row.get("final_locator", ""),
            "page_text_sha256": row.get("final_page_text_sha256", ""),
            "evidence_excerpt": row.get("final_evidence_excerpt", ""),
            "reason_code": row.get("final_reason_code", ""),
        }
        if truth[key]["status"] not in REVIEW_STATUSES:
            raise ReviewPackageError("invalid_final_status", f"Invalid final status: {key}.")
        decision = truth[key]
        if decision["status"] == "located":
            required = (
                "title_raw",
                "page_start",
                "page_end",
                "scope",
                "period_end",
                "locator",
                "page_text_sha256",
                "evidence_excerpt",
            )
            if any(not decision[field].strip() for field in required):
                raise ReviewPackageError(
                    "missing_final_locator_field", f"Adjudicated target incomplete: {key}."
                )
            report = reports_by_code[targets[key]["security_code"]]
            start = _parse_page(decision["page_start"], "final_page_start", int(report["pages"]))
            end = _parse_page(decision["page_end"], "final_page_end", int(report["pages"]))
            if end < start or decision["scope"] != "consolidated":
                raise ReviewPackageError(
                    "invalid_final_locator", f"Invalid adjudicated range for {key}."
                )
            if not re.fullmatch(r"[0-9a-f]{64}", decision["page_text_sha256"]):
                raise ReviewPackageError(
                    "invalid_final_page_hash", f"Invalid adjudicated page hash for {key}."
                )
            if verify_page_hashes:
                _verify_page_hash(decision, report, data_root, page_hash_cache)
        elif not decision["reason_code"].strip() or not decision["evidence_excerpt"].strip():
            raise ReviewPackageError(
                "missing_final_reason",
                f"Adjudicated missing/ambiguous target needs evidence and reason: {key}.",
            )
    return truth


def _machine_index(machine: dict[str, Any]) -> dict[tuple[str, str], dict[str, str]]:
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for report in machine.get("results", []):
        code = str(report["security_code"])
        sample_id = f"{code}-2024"
        for statement_type, statement in report.get("statements", {}).items():
            key = (sample_id, statement_type)
            if key in indexed or statement_type not in STATEMENT_TYPES:
                raise ReviewPackageError(
                    "invalid_machine_results", f"Duplicate or unsupported machine target: {key}."
                )
            indexed[key] = {
                "status": str(statement.get("status", report.get("status", ""))),
                "scope": str(statement.get("scope", "")),
                "period_end": str(statement.get("period_end", "")),
                "page_start": str(statement.get("page_number", "")),
                "page_end": str(statement.get("page_end", "")),
            }
    return indexed


def _score_machine(
    truth: dict[tuple[str, str], dict[str, str]], machine: dict[str, Any]
) -> dict[str, Any]:
    machine_rows = _machine_index(machine)
    essential_fields = ("status", "scope", "period_end", "page_start")
    differences: list[dict[str, Any]] = []
    by_type: dict[str, dict[str, int]] = {
        statement: {"targets": 0, "essential_exact": 0, "page_end_exact": 0}
        for statement in sorted(STATEMENT_TYPES)
    }
    essential_exact = 0
    page_end_exact = 0
    for key, expected in sorted(truth.items()):
        actual = machine_rows.get(key, {})
        mismatches = [
            field for field in essential_fields if actual.get(field, "") != expected[field]
        ]
        page_end_matches = actual.get("page_end", "") == expected.get("page_end", "")
        bucket = by_type[key[1]]
        bucket["targets"] += 1
        if not mismatches:
            essential_exact += 1
            bucket["essential_exact"] += 1
        if page_end_matches:
            page_end_exact += 1
            bucket["page_end_exact"] += 1
        if mismatches or not page_end_matches:
            differences.append(
                {
                    "sample_id": key[0],
                    "statement_type": key[1],
                    "essential_mismatches": mismatches,
                    "page_end_matches": page_end_matches,
                    "expected": {
                        field: expected.get(field, "") for field in (*essential_fields, "page_end")
                    },
                    "actual": {
                        field: actual.get(field, "") for field in (*essential_fields, "page_end")
                    },
                }
            )
    total = len(truth)
    return {
        "targets": total,
        "essential_exact": essential_exact,
        "essential_exact_rate": essential_exact / total,
        "page_end_exact": page_end_exact,
        "page_end_exact_rate": page_end_exact / total,
        "gate_passed": essential_exact == total,
        "by_statement_type": by_type,
        "differences": differences,
    }


def evaluate_review_package(
    manifest: dict[str, Any],
    queue: list[dict[str, str]],
    reviewer_a: list[dict[str, str]],
    reviewer_b: list[dict[str, str]],
    adjudications: list[dict[str, str]],
    machine: dict[str, Any],
    data_root: Path,
    *,
    verify_page_hashes: bool = True,
) -> dict[str, Any]:
    """Return an auditable waiting or scored result; invalid packages raise."""

    targets = validate_corpus(manifest, queue, data_root)
    reports = {str(row["security_code"]): row for row in manifest["reports"]}
    a_id, a_rows = _validate_submission(
        reviewer_a, targets, reports, data_root, verify_page_hashes=verify_page_hashes
    )
    b_id, b_rows = _validate_submission(
        reviewer_b, targets, reports, data_root, verify_page_hashes=verify_page_hashes
    )
    base: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": {"reports": 10, "targets": 30},
        "limitations": [
            "F004 qualification evidence only; do not extrapolate to F005-F018 accuracy."
        ],
    }
    if not a_rows and not b_rows:
        return {
            **base,
            "status": "awaiting_independent_review",
            "blockers": ["reviewer_a_missing", "reviewer_b_missing"],
            "agreement": None,
            "machine_score": None,
        }
    if not a_rows or not b_rows:
        raise ReviewPackageError("partial_review_package", "Both independent reviews are required.")
    if a_id == b_id:
        raise ReviewPackageError("role_conflict", "Reviewer A and Reviewer B must be distinct.")

    field_matches = Counter({field: 0 for field in COMPARISON_FIELDS})
    conflicts: list[tuple[str, str]] = []
    truth: dict[tuple[str, str], dict[str, str]] = {}
    for key in sorted(targets):
        matches = [_same(a_rows[key], b_rows[key], field) for field in COMPARISON_FIELDS]
        for field, matches_field in zip(COMPARISON_FIELDS, matches, strict=True):
            field_matches[field] += int(matches_field)
        if all(matches):
            truth[key] = a_rows[key]
        else:
            conflicts.append(key)
    if conflicts:
        truth.update(
            _adjudicated_truth(
                conflicts,
                adjudications,
                {a_id, b_id},
                targets,
                reports,
                data_root,
                verify_page_hashes=verify_page_hashes,
            )
        )
    elif any(row.get("adjudication_status", "").strip() for row in adjudications):
        raise ReviewPackageError(
            "unexpected_adjudication", "No-conflict package needs no adjudication."
        )

    authorization = str(manifest.get("source_authorization", ""))
    if not authorization or "pending" in authorization.lower():
        raise ReviewPackageError(
            "source_authorization_pending", "Corpus use basis must be resolved before scoring."
        )
    total = len(targets)
    agreement = {
        "targets": total,
        "exact_target_agreement": total - len(conflicts),
        "exact_target_agreement_rate": (total - len(conflicts)) / total,
        "conflicts": len(conflicts),
        "conflict_rate": len(conflicts) / total,
        "adjudicated": len(conflicts),
        "adjudication_rate": len(conflicts) / total,
        "field_agreement_rates": {
            field: field_matches[field] / total for field in COMPARISON_FIELDS
        },
        "final_status_distribution": dict(Counter(row["status"] for row in truth.values())),
    }
    machine_score = _score_machine(truth, machine)
    return {
        **base,
        "status": "passed" if machine_score["gate_passed"] else "failed",
        "blockers": [],
        "agreement": agreement,
        "machine_score": machine_score,
    }
