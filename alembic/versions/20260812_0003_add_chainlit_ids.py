"""Add stable Chainlit identifiers to application-owned chat records.

Revision ID: 20260812_0003
Revises: 20260811_0002
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0003"
down_revision: str | None = "20260811_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist UI identifiers without overloading provider identifiers."""
    op.add_column("messages", sa.Column("chainlit_step_id", sa.String(255), nullable=True))
    op.create_index(
        "ix_messages_chainlit_step_id",
        "messages",
        ["chainlit_step_id"],
        unique=True,
    )
    op.add_column(
        "message_attachments",
        sa.Column("chainlit_element_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_message_attachments_chainlit_element_id",
        "message_attachments",
        ["chainlit_element_id"],
        unique=True,
    )
    op.add_column(
        "chat_feedback",
        sa.Column("chainlit_feedback_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_chat_feedback_chainlit_feedback_id",
        "chat_feedback",
        ["chainlit_feedback_id"],
        unique=True,
    )


def downgrade() -> None:
    """Remove Chainlit-specific stable identifiers."""
    op.drop_index("ix_chat_feedback_chainlit_feedback_id", table_name="chat_feedback")
    op.drop_column("chat_feedback", "chainlit_feedback_id")
    op.drop_index(
        "ix_message_attachments_chainlit_element_id",
        table_name="message_attachments",
    )
    op.drop_column("message_attachments", "chainlit_element_id")
    op.drop_index("ix_messages_chainlit_step_id", table_name="messages")
    op.drop_column("messages", "chainlit_step_id")
