"""Create F004 statement-identification outcomes.

Revision ID: 20260906_0004
Revises: 20260906_0003
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0004"
down_revision: str | None = "20260906_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist one deterministic identification result per required statement type."""

    op.create_table(
        "statement_identifications",
        sa.Column("statement_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("statement_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("table_id", sa.String(length=64), nullable=True),
        sa.Column("locator", sa.JSON(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("reason", sa.JSON(), nullable=True),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "statement_type IN ('balance_sheet', 'income_statement', 'cashflow_statement')",
            name="statement_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_documents.source_id"],
            name="fk_statement_identifications_source_id_source_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("statement_id", name="pk_statement_identifications"),
        sa.UniqueConstraint(
            "source_id", "statement_type", name="uq_statement_identifications_source_type"
        ),
    )
    op.create_index(
        "ix_statement_identifications_source_id",
        "statement_identifications",
        ["source_id"],
    )


def downgrade() -> None:
    """Remove F004 identification outcomes."""

    op.drop_index("ix_statement_identifications_source_id", table_name="statement_identifications")
    op.drop_table("statement_identifications")
