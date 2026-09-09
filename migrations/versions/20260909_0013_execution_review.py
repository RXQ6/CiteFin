from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0013"
down_revision: str | None = "20260909_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_executions",
        sa.Column("execution_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_node", sa.String(64)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id", name="pk_analysis_executions"),
        sa.UniqueConstraint("run_id", name="uq_analysis_executions_run_id"),
    )
    op.create_index("ix_analysis_executions_status", "analysis_executions", ["status"])
    op.create_table(
        "review_items",
        sa.Column("item_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("item_type", sa.String(64), nullable=False),
        sa.Column("checkpoint_node", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", name="pk_review_items"),
    )
    op.create_index("ix_review_items_run_id", "review_items", ["run_id"])
    op.create_index("ix_review_items_status", "review_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_review_items_status", table_name="review_items")
    op.drop_index("ix_review_items_run_id", table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_analysis_executions_status", table_name="analysis_executions")
    op.drop_table("analysis_executions")
