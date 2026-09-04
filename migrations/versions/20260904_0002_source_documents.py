"""Create F002 immutable source-document storage.

Revision ID: 20260904_0002
Revises: 20260904_0001
Create Date: 2026-09-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0002"
down_revision: str | None = "20260904_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create global immutable objects and run-scoped source references."""

    op.create_table(
        "stored_objects",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("sha256", name="pk_stored_objects"),
        sa.UniqueConstraint("storage_uri", name="uq_stored_objects_storage_uri"),
    )
    op.create_table(
        "source_documents",
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("document_type", sa.String(length=32), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=True),
        sa.Column("security_code", sa.String(length=6), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("text_extractable", sa.Boolean(), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["analysis_runs.run_id"],
            name="fk_source_documents_run_id_analysis_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sha256"],
            ["stored_objects.sha256"],
            name="fk_source_documents_sha256_stored_objects",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_source_documents"),
        sa.UniqueConstraint(
            "run_id", "sha256", name="uq_source_documents_run_id_sha256"
        ),
    )
    op.create_index("ix_source_documents_run_id", "source_documents", ["run_id"])
    op.create_index("ix_source_documents_sha256", "source_documents", ["sha256"])


def downgrade() -> None:
    """Remove source references before immutable object metadata."""

    op.drop_index("ix_source_documents_sha256", table_name="source_documents")
    op.drop_index("ix_source_documents_run_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_table("stored_objects")
