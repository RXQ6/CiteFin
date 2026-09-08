"""Trust-boundary tests for independent F004 review validation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter

from citefin.review_validation import (
    RESULT_SCHEMA_VERSION,
    SUBMISSION_SCHEMA_VERSION,
    ReviewPackageError,
    evaluate_review_package,
)

STATEMENTS = ("balance_sheet", "income_statement", "cashflow_statement")


def _package(
    tmp_path: Path,
) -> tuple[
    dict[str, Any],
    list[dict[str, str]],
    list[dict[str, str]],
    list[dict[str, str]],
    dict[str, Any],
]:
    reports: list[dict[str, Any]] = []
    queue: list[dict[str, str]] = []
    machine_results: list[dict[str, Any]] = []
    for number in range(10):
        code = f"{number:06d}"
        file_name = f"{code}.pdf"
        path = tmp_path / file_name
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(path)
        reports.append(
            {
                "security_code": code,
                "company_name": f"Company {code}",
                "report_year": 2024,
                "file": file_name,
                "bytes": path.stat().st_size,
                "pages": 1,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
        statements: dict[str, Any] = {}
        for statement in STATEMENTS:
            queue.append(
                {
                    "sample_id": f"{code}-2024",
                    "security_code": code,
                    "company_name": f"Company {code}",
                    "report_year": "2024",
                    "statement_type": statement,
                }
            )
            statements[statement] = {
                "page_number": 1,
                "page_end": 1,
                "scope": "consolidated",
                "period_end": "2024-12-31",
            }
        machine_results.append(
            {"security_code": code, "status": "located", "statements": statements}
        )
    manifest = {
        "source_authorization": "public disclosure; approved internal evaluation use",
        "reports": reports,
    }
    blank = [_review_row(row, "", "") for row in queue]
    machine = {"results": machine_results}
    return manifest, queue, blank, deepcopy(blank), machine


def _review_row(target: dict[str, str], reviewer_id: str, status: str) -> dict[str, str]:
    return {
        "schema_version": SUBMISSION_SCHEMA_VERSION,
        **target,
        "reviewer_id": reviewer_id,
        "status": status,
        "title_raw": "合并财务报表" if status else "",
        "page_start": "1" if status else "",
        "page_end": "1" if status else "",
        "scope": "consolidated" if status else "",
        "period_end": "2024-12-31" if status else "",
        "locator": "pdf_page=1" if status else "",
        "page_text_sha256": "0" * 64 if status else "",
        "evidence_excerpt": "合并财务报表；2024 年度" if status else "",
        "reason_code": "",
        "reviewed_at": "2026-09-08T09:00:00+08:00" if status else "",
    }


def _complete(rows: list[dict[str, str]], reviewer_id: str) -> list[dict[str, str]]:
    return [_review_row(row, reviewer_id, "located") for row in rows]


def _evaluate(
    package: tuple[
        dict[str, Any],
        list[dict[str, str]],
        list[dict[str, str]],
        list[dict[str, str]],
        dict[str, Any],
    ],
    tmp_path: Path,
    *,
    adjudications: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    manifest, queue, reviewer_a, reviewer_b, machine = package
    return evaluate_review_package(
        manifest,
        queue,
        reviewer_a,
        reviewer_b,
        adjudications or [],
        machine,
        tmp_path,
        verify_page_hashes=False,
    )


def test_blank_package_is_explicitly_awaiting_review(tmp_path: Path) -> None:
    result = _evaluate(_package(tmp_path), tmp_path)
    assert result["schema_version"] == RESULT_SCHEMA_VERSION
    assert result["status"] == "awaiting_independent_review"
    assert result["machine_score"] is None


def test_partial_submission_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][0] = _review_row(package[1][0], "human-a01", "located")
    with pytest.raises(ReviewPackageError, match="complete all targets"):
        _evaluate(package, tmp_path)


def test_queue_identity_must_match_immutable_manifest(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[1][0]["company_name"] = "Different Company"

    with pytest.raises(ReviewPackageError, match="identity mismatch"):
        _evaluate(package, tmp_path)


def test_submission_columns_must_match_versioned_template(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][0]["unexpected"] = "field"

    with pytest.raises(ReviewPackageError, match="columns"):
        _evaluate(package, tmp_path)


@pytest.mark.parametrize("reviewer_id", ["reviewer_a", "codex-reviewer", "gpt-5"])
def test_placeholder_or_model_reviewer_is_rejected(tmp_path: Path, reviewer_id: str) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], reviewer_id)
    package[3][:] = _complete(package[1], "human-b01")
    with pytest.raises(ReviewPackageError, match=r"human-\*"):
        _evaluate(package, tmp_path)


def test_reviewer_roles_must_be_distinct(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-r01")
    package[3][:] = _complete(package[1], "human-r01")
    with pytest.raises(ReviewPackageError, match="distinct"):
        _evaluate(package, tmp_path)


def test_invalid_page_and_hash_are_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[2][0]["page_start"] = "2"
    with pytest.raises(ReviewPackageError, match="outside"):
        _evaluate(package, tmp_path)

    package[2][0]["page_start"] = "1"
    package[2][0]["page_text_sha256"] = "not-a-hash"
    with pytest.raises(ReviewPackageError, match="Invalid page hash"):
        _evaluate(package, tmp_path)


def test_unadjudicated_conflict_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[3][0]["title_raw"] = "不同标题"
    with pytest.raises(ReviewPackageError, match="exactly match review conflicts"):
        _evaluate(package, tmp_path)


def _adjudication(target: dict[str, str], adjudicator_id: str = "human-c01") -> dict[str, str]:
    return {
        "schema_version": SUBMISSION_SCHEMA_VERSION,
        "sample_id": target["sample_id"],
        "statement_type": target["statement_type"],
        "adjudicator_id": adjudicator_id,
        "adjudication_status": "adjudicated",
        "final_status": "located",
        "final_title_raw": "合并财务报表",
        "final_page_start": "1",
        "final_page_end": "1",
        "final_scope": "consolidated",
        "final_period_end": "2024-12-31",
        "final_locator": "pdf_page=1",
        "final_page_text_sha256": "0" * 64,
        "final_evidence_excerpt": "合并财务报表；2024 年度",
        "final_reason_code": "",
        "adjudication_reason": "复核原始 PDF 后采用该定位。",
        "adjudicated_at": "2026-09-08T10:00:00+08:00",
    }


def test_blank_adjudication_template_is_ignored_when_reviews_agree(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    blank_template = [
        {
            "schema_version": SUBMISSION_SCHEMA_VERSION,
            "sample_id": row["sample_id"],
            "statement_type": row["statement_type"],
        }
        for row in package[1]
    ]

    result = _evaluate(package, tmp_path, adjudications=blank_template)

    assert result["status"] == "passed"


def test_conflict_can_be_adjudicated_by_a_distinct_human(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[3][0]["title_raw"] = "不同标题"

    result = _evaluate(package, tmp_path, adjudications=[_adjudication(package[1][0])])

    assert result["agreement"]["conflicts"] == 1
    assert result["agreement"]["adjudicated"] == 1
    assert result["status"] == "passed"


def test_adjudicator_cannot_reuse_a_reviewer_identity(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[3][0]["title_raw"] = "不同标题"

    with pytest.raises(ReviewPackageError, match="distinct"):
        _evaluate(
            package,
            tmp_path,
            adjudications=[_adjudication(package[1][0], "human-a01")],
        )


def test_adjudicated_locator_must_be_complete_and_valid(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[3][0]["title_raw"] = "不同标题"
    decision = _adjudication(package[1][0])
    decision["final_page_start"] = ""

    with pytest.raises(ReviewPackageError, match="incomplete"):
        _evaluate(package, tmp_path, adjudications=[decision])


def test_adjudication_columns_must_match_versioned_template(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[3][0]["title_raw"] = "不同标题"
    decision = _adjudication(package[1][0])
    decision["unexpected"] = "field"

    with pytest.raises(ReviewPackageError, match="columns"):
        _evaluate(package, tmp_path, adjudications=[decision])


def test_review_timestamp_requires_an_explicit_offset(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[2][0]["reviewed_at"] = "2026-09-08T09:00:00"

    with pytest.raises(ReviewPackageError, match="UTC offset"):
        _evaluate(package, tmp_path)


def test_evidence_hash_difference_requires_adjudication(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[3][0]["page_text_sha256"] = "1" * 64

    with pytest.raises(ReviewPackageError, match="exactly match review conflicts"):
        _evaluate(package, tmp_path)


def test_duplicate_machine_target_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    package[4]["results"].append(deepcopy(package[4]["results"][0]))

    with pytest.raises(ReviewPackageError, match="Duplicate"):
        _evaluate(package, tmp_path)


def test_complete_independent_package_scores_machine_output(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")

    result = _evaluate(package, tmp_path)

    assert result["status"] == "passed"
    assert result["agreement"]["exact_target_agreement"] == 30
    assert result["machine_score"]["essential_exact"] == 30
    assert result["machine_score"]["page_end_exact"] == 30


def test_source_use_basis_must_be_resolved_before_scoring(tmp_path: Path) -> None:
    package = _package(tmp_path)
    package[0]["source_authorization"] = "internal use basis pending"
    package[2][:] = _complete(package[1], "human-a01")
    package[3][:] = _complete(package[1], "human-b01")
    with pytest.raises(ReviewPackageError, match="use basis"):
        _evaluate(package, tmp_path)


def test_versioned_schema_files_are_well_formed() -> None:
    root = Path(__file__).resolve().parents[2] / "docs" / "schemas"
    submission = json.loads((root / "f004-review-submission-v1.schema.json").read_text())
    result = json.loads((root / "f004-review-result-v1.schema.json").read_text())
    assert submission["items"]["properties"]["schema_version"]["const"] == SUBMISSION_SCHEMA_VERSION
    assert result["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
