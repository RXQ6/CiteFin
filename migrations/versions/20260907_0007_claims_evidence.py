"""Create F007 claims and evidence links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0007"
down_revision: str | None = "20260907_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist atomic claims and exactly-one-target evidence links."""

    op.create_table(
        "claims",
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("materiality", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "claim_type IN ('fact', 'calculation', 'inference', 'limitation')",
            name="claim_type_allowed",
        ),
        sa.CheckConstraint(
            "materiality IN ('major', 'minor')", name="claim_materiality_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'supported', 'unsupported', 'rejected')",
            name="claim_status_allowed",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("claim_id", name="pk_claims"),
    )
    op.create_index("ix_claims_run_id", "claims", ["run_id"])
    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.String(length=64), nullable=False),
        sa.Column("claim_id", sa.String(length=64), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=True),
        sa.Column("fact_id", sa.String(length=64), nullable=True),
        sa.Column("metric_id", sa.String(length=64), nullable=True),
        sa.Column("rule_id", sa.String(length=128), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("supports", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_type IN ('source_locator', 'fact', 'metric', 'rule')",
            name="evidence_type_allowed",
        ),
        sa.CheckConstraint(
            "supports IN ('supports', 'contradicts', 'qualifies')",
            name="evidence_supports_allowed",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.claim_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["source_documents.source_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fact_id"], ["financial_facts.fact_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["metric_id"], ["calculated_metrics.metric_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("evidence_id", name="pk_evidence"),
    )
    op.create_index("ix_evidence_claim_id", "evidence", ["claim_id"])
    op.create_index("ix_evidence_source_id", "evidence", ["source_id"])
    op.create_index("ix_evidence_fact_id", "evidence", ["fact_id"])
    op.create_index("ix_evidence_metric_id", "evidence", ["metric_id"])


def downgrade() -> None:
    """Remove F007 claim and evidence tables."""

    op.drop_index("ix_evidence_metric_id", table_name="evidence")
    op.drop_index("ix_evidence_fact_id", table_name="evidence")
    op.drop_index("ix_evidence_source_id", table_name="evidence")
    op.drop_index("ix_evidence_claim_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_claims_run_id", table_name="claims")
    op.drop_table("claims")
