"""Create F003 page-level PDF parsing records.

Revision ID: 20260906_0003
Revises: 20260904_0002
Create Date: 2026-09-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0003"
down_revision: str | None = "20260904_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable page text, locator references, and parse outcomes."""

    op.create_table(
        "document_pages",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("bbox_index_uri", sa.Text(), nullable=True),
        sa.Column("bbox_index_sha256", sa.String(length=64), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="page_number_positive"),
        sa.ForeignKeyConstraint(
            ["bbox_index_sha256"],
            ["stored_objects.sha256"],
            name="fk_document_pages_bbox_index_sha256_stored_objects",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_documents.source_id"],
            name="fk_document_pages_source_id_source_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", "page_number", name="pk_document_pages"),
    )


def downgrade() -> None:
    """Remove page records while retaining immutable objects."""

    op.drop_table("document_pages")
