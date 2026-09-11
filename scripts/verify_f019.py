"""Verify the F019 auditable report-visualization contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Validate catalog state and the visualization service/API contracts."""

    catalog = json.loads((ROOT / "FEATURES.json").read_text(encoding="utf-8"))
    feature = next(item for item in catalog["features"] if item["id"] == "F019")
    assert feature["status"] == "candidate_complete"
    assert feature["owner"] == "codex"
    assert feature["verification"]["real_report_accuracy_claim"] == "prohibited"
    assert feature["verification"]["evidence"]

    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f019-verify-", dir=tmp_root) as temp_dir:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_visualizations.py",
                "tests/integration/test_reports_api.py",
                "tests/integration/test_demo_api.py",
                "-q",
                "--no-cov",
                "--basetemp",
                str(Path(temp_dir) / "pytest"),
                "-p",
                "no:cacheprovider",
            ],
            cwd=ROOT,
            check=True,
        )
    print("F019 verifier passed: versioned specs, provenance, hashes, API, and omissions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
