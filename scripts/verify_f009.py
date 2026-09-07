"""Run the machine-verifiable provisional acceptance checks for F009."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    """Run a project command and fail with its exit code."""

    print(f"$ {' '.join(command)}")
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def main() -> int:
    """Verify deterministic claims, evidence links, and replay behavior."""

    tmp_root = PROJECT_ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f009-verify-", dir=tmp_root) as temp_dir:
        pytest_temp_path = Path(temp_dir) / "pytest"
        pytest_temp_path.mkdir()
        env = os.environ.copy()
        env["CITEFIN_DATABASE_URL"] = f"sqlite+pysqlite:///{Path(temp_dir) / 'f009.db'}"
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_financial_analysis.py",
                "tests/integration/test_financial_analysis_api.py",
                "-q",
                "--no-cov",
                "--basetemp",
                str(pytest_temp_path),
                "-p",
                "no:cacheprovider",
            ],
            env=env,
        )

    print("F009 verifier passed: deterministic claims and evidence-backed analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
