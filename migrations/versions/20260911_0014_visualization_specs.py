from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0014"
down_revision: str | None = "20260909_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "visualization_specs",
        sa.Column("visualization_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("report_id", sa.String(64), nullable=False),
        sa.Column("chart_key", sa.String(64), nullable=False),
        sa.Column("spec_version", sa.String(64), nullable=False),
        sa.Column("chart_type", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("dataset", sa.JSON(), nullable=False),
        sa.Column("encoding", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("data_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("renderer_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "chart_type IN ('bar', 'grouped_bar')",
            name="visualization_chart_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('validated', 'invalid')",
            name="visualization_status_allowed",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.report_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("visualization_id", name="pk_visualization_specs"),
        sa.UniqueConstraint(
            "report_id",
            "chart_key",
            "spec_version",
            name="uq_visualization_specs_report_key_version",
        ),
    )
    op.create_index("ix_visualization_specs_run_id", "visualization_specs", ["run_id"])
    op.create_index("ix_visualization_specs_report_id", "visualization_specs", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_visualization_specs_report_id", table_name="visualization_specs")
    op.drop_index("ix_visualization_specs_run_id", table_name="visualization_specs")
    op.drop_table("visualization_specs")
