from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0010"
down_revision: str | None = "20260907_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist independent evaluation inputs, checks, and repair guidance."""

    op.create_table(
        "evaluations",
        sa.Column("evaluation_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("evaluator_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.Column("blocking_reasons", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("node_hint", sa.String(length=64)),
        sa.Column("repair_instruction", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'error')",
            name="evaluation_status_allowed",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.report_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("evaluation_id", name="pk_evaluations"),
        sa.UniqueConstraint(
            "report_id", "evaluator_version", name="uq_evaluations_report_evaluator"
        ),
    )
    op.create_index("ix_evaluations_run_id", "evaluations", ["run_id"])
    op.create_index("ix_evaluations_report_id", "evaluations", ["report_id"])


def downgrade() -> None:
    """Remove F012 evaluations."""

    op.drop_index("ix_evaluations_report_id", table_name="evaluations")
    op.drop_index("ix_evaluations_run_id", table_name="evaluations")
    op.drop_table("evaluations")
