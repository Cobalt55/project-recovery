"""Add a separately hashed CSRF secret to browser sessions.

Revision ID: 20260811_0002
Revises: 20260811_0001
Create Date: 2026-08-11
"""

from collections.abc import Sequence
import hashlib
import secrets

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0002"
down_revision: str | None = "20260811_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Store only the SHA-256 hash of a separate CSRF token."""
    op.add_column(
        "login_sessions",
        sa.Column("csrf_token_hash", sa.String(length=64), nullable=True),
    )
    sessions = sa.table(
        "login_sessions",
        sa.column("id", sa.Uuid()),
        sa.column("csrf_token_hash", sa.String(length=64)),
    )
    connection = op.get_bind()
    session_ids = connection.execute(sa.select(sessions.c.id)).scalars()
    for session_id in session_ids:
        connection.execute(
            sessions.update()
            .where(sessions.c.id == session_id)
            .values(csrf_token_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest())
        )
    op.alter_column("login_sessions", "csrf_token_hash", nullable=False)
    op.create_unique_constraint(
        "uq_login_sessions_csrf_token_hash", "login_sessions", ["csrf_token_hash"]
    )


def downgrade() -> None:
    """Remove the CSRF hash column."""
    op.drop_constraint("uq_login_sessions_csrf_token_hash", "login_sessions", type_="unique")
    op.drop_column("login_sessions", "csrf_token_hash")
