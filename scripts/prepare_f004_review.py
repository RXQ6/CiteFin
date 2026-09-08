"""Validate the frozen F004 corpus and create blank blind-review copies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from citefin.review_validation import (
    ADJUDICATION_COLUMNS,
    REVIEW_COLUMNS,
    SUBMISSION_SCHEMA_VERSION,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "real_reports"
MANIFEST_PATH = DATA_ROOT / "manifest.json"
QUEUE_PATH = DATA_ROOT / "review_queue.csv"
STATEMENT_TYPES = {"balance_sheet", "income_statement", "cashflow_statement"}


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON object."""

    return json.loads(path.read_text(encoding="utf-8"))


def validate_corpus(manifest: dict[str, Any], queue: list[dict[str, str]]) -> None:
    """Validate frozen files and the complete 30-target queue."""

    reports = manifest["reports"]
    if len(reports) != 10:
        raise ValueError(f"expected 10 reports, found {len(reports)}")
    expected_targets = {(row["sample_id"], row["statement_type"]) for row in queue}
    if len(queue) != 30 or len(expected_targets) != 30:
        raise ValueError("review queue must contain 30 unique targets")
    if not all(row["statement_type"] in STATEMENT_TYPES for row in queue):
        raise ValueError("review queue contains an unsupported statement type")

    for report in reports:
        path = DATA_ROOT / report["file"]
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != report["bytes"]:
            raise ValueError(f"byte count mismatch: {path.name}")
        if sha256_file(path) != report["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {path.name}")
        if len(PdfReader(str(path)).pages) != report["pages"]:
            raise ValueError(f"page count mismatch: {path.name}")


def write_blind_copy(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write one blank reviewer copy without machine labels."""

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "schema_version": SUBMISSION_SCHEMA_VERSION,
                    "sample_id": row["sample_id"],
                    "security_code": row["security_code"],
                    "company_name": row["company_name"],
                    "report_year": row["report_year"],
                    "statement_type": row["statement_type"],
                    "reviewer_id": "",
                    "status": "",
                    "title_raw": "",
                    "page_start": "",
                    "page_end": "",
                    "scope": "",
                    "period_end": "",
                    "locator": "",
                    "page_text_sha256": "",
                    "evidence_excerpt": "",
                    "reason_code": "",
                    "reviewed_at": "",
                }
            )


def write_adjudication_template(rows: list[dict[str, str]], output_path: Path) -> None:
    """Write an empty conflict-only template without reviewer or machine answers."""

    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ADJUDICATION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "schema_version": SUBMISSION_SCHEMA_VERSION,
                    "sample_id": row["sample_id"],
                    "statement_type": row["statement_type"],
                }
            )


def write_readme(output_dir: Path, manifest: dict[str, Any]) -> None:
    """Explain the handoff and its blind-review boundary."""

    text = f"""# F004 blind-review handoff

Corpus manifest date: {manifest["collected_at"]}

This directory contains two blank, identical review copies for independent reviewers.
The copies contain only target identity fields; all answer and evidence fields are blank.

- `reviewer_a.csv`: Reviewer A only
- `reviewer_b.csv`: Reviewer B only
- `adjudication.csv`: fill conflict rows only after both reviews are returned

Do not share either completed copy with the other reviewer. Do not provide machine
preannotations to either reviewer. Use the rules in `docs/F004_REVIEW_PACKET.md` and
return the completed CSV with the original PDF evidence preserved. Completed reviewers
and the adjudicator must use distinct opaque IDs matching `human-*`; do not store names
or other personal information in the package.
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def main() -> int:
    """Validate the corpus and materialize the two blank reviewer copies."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "f004_review",
    )
    args = parser.parse_args()

    manifest = load_json(MANIFEST_PATH)
    with QUEUE_PATH.open(encoding="utf-8-sig", newline="") as file:
        queue = list(csv.DictReader(file))
    validate_corpus(manifest, queue)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_blind_copy(queue, args.output_dir / "reviewer_a.csv")
    write_blind_copy(queue, args.output_dir / "reviewer_b.csv")
    write_adjudication_template(queue, args.output_dir / "adjudication.csv")
    write_readme(args.output_dir, manifest)
    print(f"validated {len(manifest['reports'])} reports and {len(queue)} targets")
    print(f"created blank blind-review copies in {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
