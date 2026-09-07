from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0011"
down_revision: str | None = "20260907_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist auditable Goal Gate terminal decisions."""

    op.create_table(
        "goal_gate_decisions",
        sa.Column("gate_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("evaluation_id", sa.String(length=64), nullable=True),
        sa.Column("gate_version", sa.String(length=128), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("blocking_reasons", sa.JSON(), nullable=False),
        sa.Column("node_hint", sa.String(length=64)),
        sa.Column("repair_instruction", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('verified', 'revision_required', 'blocked', 'error')",
            name="goal_gate_decision_allowed",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.report_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["evaluation_id"], ["evaluations.evaluation_id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("gate_id", name="pk_goal_gate_decisions"),
        sa.UniqueConstraint("report_id", "gate_version", name="uq_goal_gate_report_version"),
    )
    op.create_index("ix_goal_gate_decisions_run_id", "goal_gate_decisions", ["run_id"])
    op.create_index("ix_goal_gate_decisions_report_id", "goal_gate_decisions", ["report_id"])
    op.create_index(
        "ix_goal_gate_decisions_evaluation_id", "goal_gate_decisions", ["evaluation_id"]
    )


def downgrade() -> None:
    """Remove F013 Goal Gate decisions."""

    op.drop_index("ix_goal_gate_decisions_evaluation_id", table_name="goal_gate_decisions")
    op.drop_index("ix_goal_gate_decisions_report_id", table_name="goal_gate_decisions")
    op.drop_index("ix_goal_gate_decisions_run_id", table_name="goal_gate_decisions")
    op.drop_table("goal_gate_decisions")
