"""Initial durable PostgreSQL persistence schema.

Revision ID: 20260811_0001
Revises:
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_column(name: str = "id", *constraints: object, **kwargs: object) -> sa.Column[object]:
    """Build consistently typed UUID columns for the PostgreSQL schema."""
    return sa.Column(name, postgresql.UUID(as_uuid=True), *constraints, **kwargs)


def timestamp_column(name: str, **kwargs: object) -> sa.Column[object]:
    """Build timezone-aware timestamp columns."""
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    """Create all durable application tables, constraints, and page indexes."""
    op.create_table(
        "users",
        uuid_column(primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("force_password_change", sa.Boolean(), nullable=False),
        timestamp_column("created_at", nullable=False),
        timestamp_column("updated_at", nullable=False),
        timestamp_column("last_login_at", nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_is_active", "users", ["is_active"])

    op.create_table(
        "login_sessions",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        timestamp_column("created_at", nullable=False),
        timestamp_column("last_seen_at", nullable=False),
        timestamp_column("expires_at", nullable=False),
        timestamp_column("revoked_at", nullable=True),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_login_sessions_user_id", "login_sessions", ["user_id"])
    op.create_index("ix_login_sessions_expires_at", "login_sessions", ["expires_at"])
    op.create_index("ix_login_sessions_revoked_at", "login_sessions", ["revoked_at"])

    op.create_table(
        "user_management_events",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("actor_user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        uuid_column(
            "target_user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        timestamp_column("created_at", nullable=False),
    )
    op.create_index(
        "ix_user_management_events_actor_user_id", "user_management_events", ["actor_user_id"]
    )
    op.create_index(
        "ix_user_management_events_target_user_id", "user_management_events", ["target_user_id"]
    )
    op.create_index("ix_user_management_events_action", "user_management_events", ["action"])
    op.create_index(
        "ix_user_management_events_created_at", "user_management_events", ["created_at"]
    )

    op.create_table(
        "conversations",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chainlit_thread_id", sa.String(length=255), nullable=False),
        sa.Column("openai_conversation_id", sa.String(length=255), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        timestamp_column("created_at", nullable=False),
        timestamp_column("updated_at", nullable=False),
        sa.UniqueConstraint("chainlit_thread_id"),
        sa.UniqueConstraint("openai_conversation_id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])

    op.create_table(
        "messages",
        uuid_column(primary_key=True, nullable=False),
        uuid_column(
            "conversation_id", sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(length=50000), nullable=False),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        timestamp_column("created_at", nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')", name="ck_messages_role"
        ),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_provider_response_id", "messages", ["provider_response_id"])
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "message_attachments",
        uuid_column(primary_key=True, nullable=False),
        uuid_column(
            "conversation_id", sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        uuid_column("message_id", sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("provider_file_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        timestamp_column("created_at", nullable=False),
    )
    op.create_index(
        "ix_message_attachments_conversation_id", "message_attachments", ["conversation_id"]
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])
    op.create_index(
        "ix_message_attachments_provider_file_id", "message_attachments", ["provider_file_id"]
    )

    op.create_table(
        "prompt_runs",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        uuid_column(
            "conversation_id", sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("requested_reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("effective_reasoning_effort", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.String(length=16000), nullable=False),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        timestamp_column("started_at", nullable=False),
        timestamp_column("finished_at", nullable=True),
    )
    for name, columns in (
        ("ix_prompt_runs_user_id", ["user_id"]),
        ("ix_prompt_runs_conversation_id", ["conversation_id"]),
        ("ix_prompt_runs_trace_id", ["trace_id"]),
        ("ix_prompt_runs_status", ["status"]),
        ("ix_prompt_runs_provider_response_id", ["provider_response_id"]),
        ("ix_prompt_runs_started_at", ["started_at"]),
        ("ix_prompt_runs_status_started", ["status", "started_at"]),
        ("ix_prompt_runs_user_started", ["user_id", "started_at"]),
        ("ix_prompt_runs_conversation_started", ["conversation_id", "started_at"]),
    ):
        op.create_index(name, "prompt_runs", columns)

    op.create_table(
        "tool_runs",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        uuid_column(
            "conversation_id", sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        uuid_column(
            "prompt_run_id", sa.ForeignKey("prompt_runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("trace_id", sa.String(length=255), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("tool_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("result_summary", sa.String(length=2000), nullable=True),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=False),
        timestamp_column("created_at", nullable=False),
    )
    for name, columns in (
        ("ix_tool_runs_user_id", ["user_id"]),
        ("ix_tool_runs_conversation_id", ["conversation_id"]),
        ("ix_tool_runs_prompt_run_id", ["prompt_run_id"]),
        ("ix_tool_runs_trace_id", ["trace_id"]),
        ("ix_tool_runs_status", ["status"]),
        ("ix_tool_runs_created_at", ["created_at"]),
        ("ix_tool_runs_conversation_created", ["conversation_id", "created_at"]),
    ):
        op.create_index(name, "tool_runs", columns)

    op.create_table(
        "chat_feedback",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        uuid_column(
            "conversation_id", sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
        ),
        uuid_column("message_id", sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("tool_summary", sa.String(length=2000), nullable=True),
        timestamp_column("created_at", nullable=False),
        sa.CheckConstraint("rating IN (-1, 1)", name="ck_chat_feedback_rating"),
    )
    for name, columns in (
        ("ix_chat_feedback_user_id", ["user_id"]),
        ("ix_chat_feedback_conversation_id", ["conversation_id"]),
        ("ix_chat_feedback_message_id", ["message_id"]),
        ("ix_chat_feedback_trace_id", ["trace_id"]),
        ("ix_chat_feedback_created", ["created_at"]),
    ):
        op.create_index(name, "chat_feedback", columns)

    op.create_table(
        "exception_logs",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_path", sa.String(length=2048), nullable=False),
        sa.Column("exception_type", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=4000), nullable=False),
        sa.Column("stack_trace", sa.String(length=32000), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        timestamp_column("first_seen_at", nullable=False),
        timestamp_column("last_seen_at", nullable=False),
        sa.UniqueConstraint("fingerprint", "request_path", name="uq_exception_logs_group"),
    )
    for name, columns in (
        ("ix_exception_logs_user_id", ["user_id"]),
        ("ix_exception_logs_fingerprint", ["fingerprint"]),
        ("ix_exception_logs_last_seen_at", ["last_seen_at"]),
        ("ix_exception_logs_fingerprint_last_seen", ["fingerprint", "last_seen_at"]),
    ):
        op.create_index(name, "exception_logs", columns)

    op.create_table(
        "knowledge_resources",
        uuid_column(primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_file_id", sa.String(length=255), nullable=True),
        sa.Column("vector_store_file_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        timestamp_column("created_at", nullable=False),
        timestamp_column("updated_at", nullable=False),
    )
    for name, columns in (
        ("ix_knowledge_resources_name", ["name"]),
        ("ix_knowledge_resources_category", ["category"]),
        ("ix_knowledge_resources_status", ["status"]),
        ("ix_knowledge_resources_provider_file_id", ["provider_file_id"]),
        ("ix_knowledge_resources_vector_store_file_id", ["vector_store_file_id"]),
        ("ix_knowledge_resources_updated_at", ["updated_at"]),
        ("ix_knowledge_resources_status_updated", ["status", "updated_at"]),
    ):
        op.create_index(name, "knowledge_resources", columns)

    op.create_table(
        "app_settings",
        uuid_column(primary_key=True, nullable=False),
        uuid_column("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        timestamp_column("updated_at", nullable=False),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_app_settings_user_id", "app_settings", ["user_id"])


def downgrade() -> None:
    """Remove the initial schema in reverse dependency order."""
    for table_name in (
        "app_settings",
        "knowledge_resources",
        "exception_logs",
        "chat_feedback",
        "tool_runs",
        "prompt_runs",
        "message_attachments",
        "messages",
        "conversations",
        "user_management_events",
        "login_sessions",
        "users",
    ):
        op.drop_table(table_name)
