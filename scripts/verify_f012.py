"""Run focused F012 migration and independent-evaluator checks."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).parents[1]


def _run(arguments: list[str], *, env: dict[str, str]) -> None:
    completed = subprocess.run(arguments, cwd=PROJECT_ROOT, env=env, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="f012-verify-", dir=PROJECT_ROOT / "tmp") as temp:
        database_url = f"sqlite+pysqlite:///{(Path(temp) / 'f012.db').as_posix()}"
        env = os.environ.copy()
        env["CITEFIN_DATABASE_URL"] = database_url
        _run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        _run([sys.executable, "-m", "alembic", "check"], env=env)
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/unit/test_evaluation.py",
                "tests/integration/test_evaluations_api.py",
                "-q",
                "--no-cov",
                "--basetemp",
                str(Path(temp) / "pytest"),
                "-p",
                "no:cacheprovider",
            ],
            env=env,
        )
    print("F012 verifier passed: independent auditable evaluation.")


if __name__ == "__main__":
    main()
