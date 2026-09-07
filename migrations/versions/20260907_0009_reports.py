"""Create F011 structured reports."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0009"
down_revision: str | None = "20260907_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist versioned candidate reports assembled from durable evidence."""

    op.create_table(
        "reports",
        sa.Column("report_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("generated_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'candidate', 'verified', 'superseded')",
            name="report_status_allowed",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("report_id", name="pk_reports"),
        sa.UniqueConstraint("run_id", "version", name="uq_reports_run_version"),
    )
    op.create_index("ix_reports_run_id", "reports", ["run_id"])


def downgrade() -> None:
    """Remove F011 reports."""

    op.drop_index("ix_reports_run_id", table_name="reports")
    op.drop_table("reports")
