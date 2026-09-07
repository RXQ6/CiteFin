"""Create F010 deterministic risk findings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0008"
down_revision: str | None = "20260907_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist risk findings with rule, evidence, and confidence metadata."""

    op.create_table(
        "risk_findings",
        sa.Column("risk_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("risk_code", sa.String(length=128), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category IN ('profitability', 'cashflow', 'solvency', 'working_capital', 'data_quality')",
            name="risk_finding_category_allowed",
        ),
        sa.CheckConstraint(
            "severity IN ('critical', 'high', 'medium', 'low')",
            name="risk_finding_severity_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'qualified', 'dismissed')",
            name="risk_finding_status_allowed",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="risk_finding_confidence_range",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("risk_id", name="pk_risk_findings"),
        sa.UniqueConstraint(
            "run_id", "risk_code", "period_end", name="uq_risk_findings_run_code_period"
        ),
    )
    op.create_index("ix_risk_findings_run_id", "risk_findings", ["run_id"])


def downgrade() -> None:
    """Remove F010 risk findings."""

    op.drop_index("ix_risk_findings_run_id", table_name="risk_findings")
    op.drop_table("risk_findings")
