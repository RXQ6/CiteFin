"""Migration smoke test for a clean CiteFin database."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import create_engine, inspect


def test_upgrade_head_creates_analysis_run_bundle(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    database_path = tmp_path / "migration.db"
    unintended_path = tmp_path / "env-configured.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CITEFIN_DATABASE_URL", f"sqlite+pysqlite:///{unintended_path.as_posix()}")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(database_url)
    assert {
        "alembic_version",
        "analysis_runs",
        "audit_events",
        "document_pages",
        "source_documents",
        "statement_identifications",
        "stored_objects",
        "tasks",
        "risk_findings",
        "reports",
        "evaluations",
        "goal_gate_decisions",
        "workflow_checkpoints",
        "visualization_specs",
    }.issubset(inspect(engine).get_table_names())
    engine.dispose()
    assert not unintended_path.exists()
