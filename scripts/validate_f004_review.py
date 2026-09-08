"""Validate F004 blind reviews and produce a source-hashed result."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from citefin.review_validation import (
    RESULT_SCHEMA_VERSION,
    ReviewPackageError,
    evaluate_review_package,
    sha256_file,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "real_reports"
DEFAULT_REVIEW_ROOT = PROJECT_ROOT / "artifacts" / "f004_review"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-root", type=Path, default=DEFAULT_REVIEW_ROOT)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_REVIEW_ROOT / "results" / "review-validation.json"
    )
    args = parser.parse_args()
    paths = {
        "manifest": DATA_ROOT / "manifest.json",
        "queue": DATA_ROOT / "review_queue.csv",
        "reviewer_a": args.review_root / "reviewer_a.csv",
        "reviewer_b": args.review_root / "reviewer_b.csv",
        "adjudication": args.review_root / "adjudication.csv",
        "machine": DATA_ROOT / "machine_preannotations_after_fix.json",
    }
    input_hashes = {
        name: sha256_file(path) for name, path in paths.items() if path.is_file()
    }
    try:
        result = evaluate_review_package(
            load_json(paths["manifest"]),
            load_csv(paths["queue"]),
            load_csv(paths["reviewer_a"]),
            load_csv(paths["reviewer_b"]),
            load_csv(paths["adjudication"]),
            load_json(paths["machine"]),
            DATA_ROOT,
        )
        exit_code = 0 if result["status"] in {"passed", "failed"} else 2
    except ReviewPackageError as error:
        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "status": "invalid",
            "error": {"code": error.code, "message": error.message},
            "agreement": None,
            "machine_score": None,
        }
        exit_code = 1
    result["input_sha256"] = input_hashes
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
