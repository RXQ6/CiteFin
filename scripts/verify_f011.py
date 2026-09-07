"""Run machine-verifiable provisional acceptance checks for F011."""

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
    """Verify versioned report sections, evidence references, and replay behavior."""

    tmp_root = PROJECT_ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f011-verify-", dir=tmp_root) as temp_dir:
        pytest_temp_path = Path(temp_dir) / "pytest"
        pytest_temp_path.mkdir()
        env = os.environ.copy()
        env["CITEFIN_DATABASE_URL"] = f"sqlite+pysqlite:///{Path(temp_dir) / 'f011.db'}"
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        run([sys.executable, "-m", "alembic", "check"], env=env)
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_report_generation.py",
                "tests/integration/test_reports_api.py",
                "-q",
                "--no-cov",
                "--basetemp",
                str(pytest_temp_path),
                "-p",
                "no:cacheprovider",
            ],
            env=env,
        )

    print("F011 verifier passed: versioned evidence-linked candidate reports.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
