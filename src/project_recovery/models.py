"""PostgreSQL ORM records for durable application state."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Row
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-owned defaults."""
    return datetime.now(UTC)


LoginSessionListRow = Row[
    tuple[UUID, UUID, str, bool, datetime, datetime, datetime, datetime | None]
]


class Base(DeclarativeBase):
    """Declarative base shared by migrations and ORM records."""


class UUIDRecord:
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)


class User(UUIDRecord, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoginSession(UUIDRecord, Base):
    __tablename__ = "login_sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class UserManagementEvent(UUIDRecord, Base):
    __tablename__ = "user_management_events"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class Conversation(UUIDRecord, Base):
    __tablename__ = "conversations"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chainlit_thread_id: Mapped[str] = mapped_column(String(255), unique=True)
    openai_conversation_id: Mapped[str] = mapped_column(String(255), unique=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True
    )

    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class Message(UUIDRecord, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system', 'tool')", name="ck_messages_role"),
        UniqueConstraint("id", "conversation_id", name="uq_messages_id_conversation"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    chainlit_step_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String(50000))
    provider_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MessageAttachment(UUIDRecord, Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_message_attachments_message_conversation",
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=True, index=True
    )
    chainlit_element_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(127))
    byte_size: Mapped[int] = mapped_column(Integer)
    provider_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PromptRun(UUIDRecord, Base):
    __tablename__ = "prompt_runs"
    __table_args__ = (
        Index("ix_prompt_runs_status_started", "status", "started_at"),
        Index("ix_prompt_runs_user_started", "user_id", "started_at"),
        Index("ix_prompt_runs_conversation_started", "conversation_id", "started_at"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    trace_id: Mapped[str] = mapped_column(String(255), index=True)
    model: Mapped[str] = mapped_column(String(128))
    requested_reasoning_effort: Mapped[str] = mapped_column(String(16))
    effective_reasoning_effort: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), index=True)
    prompt: Mapped[str] = mapped_column(String(16000))
    provider_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolRun(UUIDRecord, Base):
    __tablename__ = "tool_runs"
    __table_args__ = (Index("ix_tool_runs_conversation_created", "conversation_id", "created_at"),)

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    prompt_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(255), index=True)
    tool_name: Mapped[str] = mapped_column(String(128))
    tool_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class ChatFeedback(UUIDRecord, Base):
    __tablename__ = "chat_feedback"
    __table_args__ = (
        CheckConstraint("rating IN (-1, 1)", name="ck_chat_feedback_rating"),
        ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_chat_feedback_message_conversation",
        ),
        Index("ix_chat_feedback_created", "created_at"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    chainlit_feedback_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    tool_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ExceptionLog(UUIDRecord, Base):
    __tablename__ = "exception_logs"
    __table_args__ = (
        Index("ix_exception_logs_fingerprint_last_seen", "fingerprint", "last_seen_at"),
        UniqueConstraint("fingerprint", "request_path", name="uq_exception_logs_group"),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    request_path: Mapped[str] = mapped_column(String(2048))
    exception_type: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(String(4000))
    stack_trace: Mapped[str | None] = mapped_column(String(32000), nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class KnowledgeResource(UUIDRecord, Base):
    __tablename__ = "knowledge_resources"
    __table_args__ = (Index("ix_knowledge_resources_status_updated", "status", "updated_at"),)

    name: Mapped[str] = mapped_column(String(255), index=True)
    content_type: Mapped[str] = mapped_column(String(127))
    byte_size: Mapped[int] = mapped_column(Integer)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    provider_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    vector_store_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True
    )


class AppSetting(UUIDRecord, Base):
    __tablename__ = "app_settings"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


__all__ = [
    "AppSetting",
    "Base",
    "ChatFeedback",
    "Conversation",
    "ExceptionLog",
    "KnowledgeResource",
    "LoginSession",
    "Message",
    "MessageAttachment",
    "PromptRun",
    "ToolRun",
    "User",
    "UserManagementEvent",
    "utc_now",
]
