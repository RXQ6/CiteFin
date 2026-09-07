"""Run the machine-verifiable provisional acceptance checks for F007."""

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
    """Verify F007 evidence linkage and migration integrity."""

    tmp_root = PROJECT_ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="f007-verify-", dir=tmp_root) as temp_dir:
        temp_path = Path(temp_dir)
        database_path = (temp_path / "f007.db").as_posix()
        pytest_temp_path = temp_path / "pytest"
        pytest_temp_path.mkdir()
        env = os.environ.copy()
        env["CITEFIN_DATABASE_URL"] = f"sqlite+pysqlite:///{database_path}"

        run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/integration/test_evidence_api.py",
                "-q",
                "--no-cov",
                "--basetemp",
                str(pytest_temp_path),
                "-p",
                "no:cacheprovider",
            ],
            env=env,
        )
        run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        run([sys.executable, "-m", "alembic", "check"], env=env)

    print("F007 verifier passed: evidence API tests, migration upgrade, and zero-drift check.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
