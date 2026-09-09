from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0012"
down_revision: str | None = "20260907_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add hashed login challenges and revocable browser sessions."""

    op.create_table(
        "auth_login_codes",
        sa.Column("code_id", sa.String(length=64), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("request_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("code_id", name="pk_auth_login_codes"),
    )
    op.create_index("ix_auth_login_codes_email_hash", "auth_login_codes", ["email_hash"])
    op.create_index(
        "ix_auth_login_codes_request_ip_hash", "auth_login_codes", ["request_ip_hash"]
    )
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_email_hash", "auth_sessions", ["email_hash"])


def downgrade() -> None:
    """Remove browser authentication persistence."""

    op.drop_index("ix_auth_sessions_email_hash", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_auth_login_codes_request_ip_hash", table_name="auth_login_codes")
    op.drop_index("ix_auth_login_codes_email_hash", table_name="auth_login_codes")
    op.drop_table("auth_login_codes")
