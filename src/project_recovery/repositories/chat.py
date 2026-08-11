"""Durable chat history persistence queries."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.models import ChatFeedback, Conversation, Message, MessageAttachment, utc_now
from project_recovery.repositories._safety import (
    bounded_text,
    page_limit,
    page_offset,
    sanitize_metadata,
)


class ChatRepository:
    """Persist application-owned conversation history without automatic expiry."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_thread(
        self,
        user_id: UUID,
        chainlit_thread_id: str,
        openai_conversation_id: str,
        settings: dict[str, object],
    ) -> Conversation:
        conversation = Conversation(
            user_id=user_id,
            chainlit_thread_id=chainlit_thread_id[:255],
            openai_conversation_id=openai_conversation_id[:255],
            settings=sanitize_metadata(settings),
        )
        async with self._sessions() as session:
            session.add(conversation)
            await session.commit()
            await session.refresh(conversation)
        return conversation

    async def get_thread(self, conversation_id: UUID) -> Conversation | None:
        async with self._sessions() as session:
            return await session.get(Conversation, conversation_id)

    async def get_thread_by_chainlit_id(self, chainlit_thread_id: str) -> Conversation | None:
        async with self._sessions() as session:
            return await session.scalar(
                select(Conversation).where(Conversation.chainlit_thread_id == chainlit_thread_id)
            )

    async def append_message(
        self, conversation_id: UUID, role: str, content: str, provider_response_id: str | None
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content[:50000],
            provider_response_id=bounded_text(provider_response_id, 255),
        )
        async with self._sessions() as session:
            session.add(message)
            conversation = await session.get(Conversation, conversation_id)
            if conversation is not None:
                conversation.updated_at = utc_now()
            await session.commit()
            await session.refresh(message)
        return message

    async def get_message(self, message_id: UUID) -> Message | None:
        async with self._sessions() as session:
            return await session.get(Message, message_id)

    async def list_messages(
        self, conversation_id: UUID, offset: int, limit: int
    ) -> Sequence[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def list_user_threads(
        self, user_id: UUID, offset: int, limit: int
    ) -> Sequence[Conversation]:
        statement = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def update_settings(
        self, conversation_id: UUID, settings: dict[str, object]
    ) -> Conversation | None:
        async with self._sessions() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            conversation.settings = sanitize_metadata(settings)
            await session.commit()
            await session.refresh(conversation)
            return conversation

    async def add_attachment(
        self,
        conversation_id: UUID,
        message_id: UUID | None,
        filename: str,
        content_type: str,
        byte_size: int,
        provider_file_id: str | None,
        metadata: dict[str, object],
    ) -> MessageAttachment:
        attachment = MessageAttachment(
            conversation_id=conversation_id,
            message_id=message_id,
            filename=filename[:255],
            content_type=content_type[:127],
            byte_size=byte_size,
            provider_file_id=bounded_text(provider_file_id, 255),
            metadata_json=sanitize_metadata(metadata),
        )
        async with self._sessions() as session:
            session.add(attachment)
            await session.commit()
            await session.refresh(attachment)
        return attachment

    async def record_feedback(
        self,
        user_id: UUID,
        conversation_id: UUID,
        message_id: UUID | None,
        rating: int,
        comment: str | None,
        context_snapshot: dict[str, object],
        model: str | None,
        trace_id: str | None,
        tool_summary: str | None,
    ) -> ChatFeedback:
        feedback = ChatFeedback(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            rating=rating,
            comment=bounded_text(comment, 2000),
            context_snapshot=sanitize_metadata(context_snapshot),
            model=bounded_text(model, 128),
            trace_id=bounded_text(trace_id, 255),
            tool_summary=bounded_text(tool_summary, 2000),
        )
        async with self._sessions() as session:
            session.add(feedback)
            await session.commit()
            await session.refresh(feedback)
        return feedback

    async def get_feedback(self, feedback_id: UUID) -> ChatFeedback | None:
        async with self._sessions() as session:
            return await session.get(ChatFeedback, feedback_id)
