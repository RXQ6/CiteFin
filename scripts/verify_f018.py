"""Run the isolated F018 synthetic end-to-end acceptance flow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Validate the catalog state and rerun both F018 terminal paths."""

    catalog = json.loads((ROOT / "FEATURES.json").read_text(encoding="utf-8"))
    feature = next(item for item in catalog["features"] if item["id"] == "F018")
    assert feature["status"] == "candidate_complete"
    assert feature["owner"] == "codex"
    assert feature["verification"]["real_report_accuracy_claim"] == "prohibited"
    assert feature["verification"]["evidence"]

    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f018-verify-", dir=tmp_root) as temp_dir:
        env = os.environ.copy()
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/e2e/test_golden_user_flow.py",
                "-q",
                "--no-cov",
                "--basetemp",
                str(Path(temp_dir) / "pytest"),
                "-p",
                "no:cacheprovider",
            ],
            cwd=ROOT,
            env=env,
            check=True,
        )
    print("F018 verifier passed: synthetic success, replay, recovery, evidence, and failed Gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
