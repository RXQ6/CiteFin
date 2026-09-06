"""Create F005 normalized financial facts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0005"
down_revision: str | None = "20260906_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist source-linked, decimal-normalized F005 facts."""

    op.create_table(
        "financial_facts",
        sa.Column("fact_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("concept", sa.String(length=96), nullable=False),
        sa.Column("label_raw", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("period_type", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("display_unit", sa.String(length=24), nullable=False),
        sa.Column("raw_value", sa.Numeric(38, 8), nullable=False),
        sa.Column("normalized_value", sa.Numeric(38, 8), nullable=False),
        sa.Column("sign_convention", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=200), nullable=False),
        sa.Column("table_id", sa.String(length=64), nullable=True),
        sa.Column("row_label", sa.Text(), nullable=False),
        sa.Column("column_label", sa.Text(), nullable=False),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("extraction_method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("validation_status", sa.String(length=16), nullable=False),
        sa.Column("mapping_version", sa.String(length=64), nullable=False),
        sa.Column("identity_key", sa.String(length=512), nullable=False),
        sa.Column("conflict_group_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "statement_type IN ('balance_sheet', 'income_statement', 'cashflow_statement')",
            name="financial_fact_statement_type_allowed",
        ),
        sa.CheckConstraint(
            "period_type IN ('instant', 'duration')",
            name="financial_fact_period_type_allowed",
        ),
        sa.CheckConstraint("scope = 'consolidated'", name="financial_fact_scope_consolidated"),
        sa.CheckConstraint(
            "display_unit IN ('yuan', 'thousand_yuan', 'million_yuan')",
            name="financial_fact_display_unit_allowed",
        ),
        sa.CheckConstraint(
            "validation_status IN ('extracted', 'conflict')",
            name="financial_fact_validation_status_allowed",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="financial_fact_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analysis_runs.run_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["source_documents.source_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("fact_id", name="pk_financial_facts"),
    )
    op.create_index("ix_financial_facts_run_id", "financial_facts", ["run_id"])
    op.create_index("ix_financial_facts_source_id", "financial_facts", ["source_id"])
    op.create_index("ix_financial_facts_identity_key", "financial_facts", ["identity_key"])
    op.create_index(
        "ix_financial_facts_conflict_group_id", "financial_facts", ["conflict_group_id"]
    )


def downgrade() -> None:
    """Remove F005 normalized financial facts."""

    op.drop_index("ix_financial_facts_conflict_group_id", table_name="financial_facts")
    op.drop_index("ix_financial_facts_identity_key", table_name="financial_facts")
    op.drop_index("ix_financial_facts_source_id", table_name="financial_facts")
    op.drop_index("ix_financial_facts_run_id", table_name="financial_facts")
    op.drop_table("financial_facts")
