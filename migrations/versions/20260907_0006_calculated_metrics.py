"""Create F006 deterministic metric results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0006"
down_revision: str | None = "20260906_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist versioned metric calculations and their input snapshots."""

    op.create_table(
        "calculated_metrics",
        sa.Column("metric_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("metric_code", sa.String(length=64), nullable=False),
        sa.Column("definition_version", sa.String(length=64), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("input_fact_ids", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("value", sa.Numeric(38, 16), nullable=True),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("calculator_version", sa.String(length=64), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('calculated', 'missing_input', 'zero_denominator', 'conflict')",
            name="calculated_metric_status_allowed",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("metric_id", name="pk_calculated_metrics"),
        sa.UniqueConstraint(
            "run_id", "metric_code", "period_end", name="uq_calculated_metrics_run_code_period"
        ),
    )
    op.create_index("ix_calculated_metrics_run_id", "calculated_metrics", ["run_id"])


def downgrade() -> None:
    """Remove F006 metric results."""

    op.drop_index("ix_calculated_metrics_run_id", table_name="calculated_metrics")
    op.drop_table("calculated_metrics")
