"""Durable chat history persistence queries."""

from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.models import ChatFeedback, Conversation, Message, MessageAttachment, utc_now
from project_recovery.repositories._safety import (
    bounded_text,
    page_limit,
    page_offset,
    sanitize_metadata,
)
from project_recovery.repositories._session import RepositoryBase


class ChatRepository(RepositoryBase):
    """Persist application-owned conversation history without automatic expiry."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession] | AsyncSession) -> None:
        super().__init__(sessions)

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
            await self._commit(session)
            await session.refresh(conversation)
        return conversation

    async def get_thread(self, conversation_id: UUID) -> Conversation | None:
        async with self._sessions() as session:
            return await session.get(Conversation, conversation_id)

    async def get_thread_by_chainlit_id(self, chainlit_thread_id: str) -> Conversation | None:
        async with self._sessions() as session:
            return cast(
                Conversation | None,
                await session.scalar(
                    select(Conversation).where(
                        Conversation.chainlit_thread_id == chainlit_thread_id
                    )
                ),
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
            await self._commit(session)
            await session.refresh(message)
        return message

    async def get_message(self, message_id: UUID) -> Message | None:
        async with self._sessions() as session:
            return await session.get(Message, message_id)

    async def get_message_by_chainlit_id(self, step_id: str) -> Message | None:
        """Resolve one application message by its stable Chainlit step ID."""
        async with self._sessions() as session:
            return cast(
                Message | None,
                await session.scalar(
                    select(Message).where(Message.chainlit_step_id == step_id[:255])
                ),
            )

    async def upsert_chainlit_message(
        self,
        *,
        conversation_id: UUID,
        step_id: str,
        role: str,
        content: str,
        provider_response_id: str | None = None,
    ) -> Message:
        """Create or update the message record owned by one Chainlit step."""
        bounded_step_id = step_id[:255]
        async with self._sessions() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                raise ValueError("conversation not found")
            statement = (
                insert(Message)
                .values(
                    conversation_id=conversation_id,
                    chainlit_step_id=bounded_step_id,
                    role=role,
                    content=content[:50000],
                    provider_response_id=bounded_text(provider_response_id, 255),
                )
                .on_conflict_do_update(
                    index_elements=[Message.chainlit_step_id],
                    set_={
                        "role": role,
                        "content": content[:50000],
                        "provider_response_id": bounded_text(provider_response_id, 255),
                    },
                    where=Message.conversation_id == conversation_id,
                )
                .returning(Message)
            )
            message = await session.scalar(statement)
            if message is None:
                raise ValueError("step belongs to a different conversation")
            conversation.updated_at = utc_now()
            await self._commit(session)
            await session.refresh(message)
            return message

    async def delete_chainlit_message(self, conversation_id: UUID, step_id: str) -> bool:
        """Delete only a step belonging to the expected conversation."""
        async with self._sessions() as session:
            result = await session.execute(
                delete(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.chainlit_step_id == step_id[:255],
                )
            )
            await self._commit(session)
            return bool(getattr(result, "rowcount", 0))

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
            await self._commit(session)
            await session.refresh(conversation)
            return conversation

    async def update_thread_details(
        self, conversation_id: UUID, *, settings: dict[str, object]
    ) -> Conversation | None:
        """Persist bounded JSON thread metadata and chat settings together."""
        return await self.update_settings(conversation_id, settings)

    async def delete_thread(self, conversation_id: UUID) -> bool:
        """Delete one user-requested thread and its cascading children."""
        async with self._sessions() as session:
            result = await session.execute(
                delete(Conversation).where(Conversation.id == conversation_id)
            )
            await self._commit(session)
            return bool(getattr(result, "rowcount", 0))

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
        async with self._sessions() as session:
            if message_id is not None:
                message = await session.get(Message, message_id)
                if message is None or message.conversation_id != conversation_id:
                    raise ValueError("message belongs to a different conversation")
            attachment = MessageAttachment(
                conversation_id=conversation_id,
                message_id=message_id,
                filename=filename[:255],
                content_type=content_type[:127],
                byte_size=byte_size,
                provider_file_id=bounded_text(provider_file_id, 255),
                metadata_json=sanitize_metadata(metadata),
            )
            session.add(attachment)
            await self._commit(session)
            await session.refresh(attachment)
        return attachment

    async def list_attachments(
        self, conversation_id: UUID, offset: int, limit: int
    ) -> Sequence[MessageAttachment]:
        """Return one bounded page of durable attachment metadata."""
        statement = (
            select(MessageAttachment)
            .where(MessageAttachment.conversation_id == conversation_id)
            .order_by(MessageAttachment.created_at.asc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def get_attachment_by_chainlit_id(
        self, conversation_id: UUID, element_id: str
    ) -> MessageAttachment | None:
        """Resolve an element only within its expected thread."""
        async with self._sessions() as session:
            return cast(
                MessageAttachment | None,
                await session.scalar(
                    select(MessageAttachment).where(
                        MessageAttachment.conversation_id == conversation_id,
                        MessageAttachment.chainlit_element_id == element_id[:255],
                    )
                ),
            )

    async def get_attachment_by_chainlit_element_id(
        self, element_id: str
    ) -> MessageAttachment | None:
        """Resolve an element globally so owner checks can recover its thread."""
        async with self._sessions() as session:
            return cast(
                MessageAttachment | None,
                await session.scalar(
                    select(MessageAttachment).where(
                        MessageAttachment.chainlit_element_id == element_id[:255]
                    )
                ),
            )

    async def upsert_chainlit_attachment(
        self,
        *,
        conversation_id: UUID,
        message_id: UUID | None,
        element_id: str,
        filename: str,
        content_type: str,
        byte_size: int,
        metadata: dict[str, object],
    ) -> MessageAttachment:
        """Create or refresh one durable Chainlit element record."""
        bounded_element_id = element_id[:255]
        async with self._sessions() as session:
            if message_id is not None:
                message = await session.get(Message, message_id)
                if message is None or message.conversation_id != conversation_id:
                    raise ValueError("message belongs to a different conversation")
            attachment = await session.scalar(
                select(MessageAttachment)
                .where(MessageAttachment.chainlit_element_id == bounded_element_id)
                .with_for_update()
            )
            if attachment is not None and attachment.conversation_id != conversation_id:
                raise ValueError("element belongs to a different conversation")
            if attachment is None:
                attachment = MessageAttachment(
                    conversation_id=conversation_id,
                    message_id=message_id,
                    chainlit_element_id=bounded_element_id,
                    filename=filename[:255],
                    content_type=content_type[:127],
                    byte_size=max(0, byte_size),
                    metadata_json=sanitize_metadata(metadata),
                )
                session.add(attachment)
            else:
                attachment.message_id = message_id
                attachment.filename = filename[:255]
                attachment.content_type = content_type[:127]
                attachment.byte_size = max(0, byte_size)
                attachment.metadata_json = sanitize_metadata(metadata)
            await self._commit(session)
            await session.refresh(attachment)
            return attachment

    async def delete_chainlit_attachment(
        self, conversation_id: UUID, element_id: str
    ) -> str | None:
        """Delete an element row and return its application-owned storage path."""
        async with self._sessions() as session:
            attachment = await session.scalar(
                select(MessageAttachment)
                .where(
                    MessageAttachment.conversation_id == conversation_id,
                    MessageAttachment.chainlit_element_id == element_id[:255],
                )
                .with_for_update()
            )
            if attachment is None:
                return None
            stored_path = attachment.metadata_json.get("path")
            await session.delete(attachment)
            await self._commit(session)
            return stored_path if isinstance(stored_path, str) else None

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
        async with self._sessions() as session:
            if message_id is not None:
                message = await session.get(Message, message_id)
                if message is None or message.conversation_id != conversation_id:
                    raise ValueError("message belongs to a different conversation")
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
            session.add(feedback)
            await self._commit(session)
            await session.refresh(feedback)
        return feedback

    async def get_feedback(self, feedback_id: UUID) -> ChatFeedback | None:
        async with self._sessions() as session:
            return await session.get(ChatFeedback, feedback_id)

    async def upsert_chainlit_feedback(
        self,
        *,
        feedback_id: str,
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
        """Create or update one Chainlit feedback action idempotently."""
        bounded_feedback_id = feedback_id[:255]
        async with self._sessions() as session:
            if message_id is not None:
                message = await session.get(Message, message_id)
                if message is None or message.conversation_id != conversation_id:
                    raise ValueError("message belongs to a different conversation")
            feedback = await session.scalar(
                select(ChatFeedback)
                .where(ChatFeedback.chainlit_feedback_id == bounded_feedback_id)
                .with_for_update()
            )
            if feedback is not None and feedback.conversation_id != conversation_id:
                raise ValueError("feedback belongs to a different conversation")
            values = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "rating": rating,
                "comment": bounded_text(comment, 2000),
                "context_snapshot": sanitize_metadata(context_snapshot),
                "model": bounded_text(model, 128),
                "trace_id": bounded_text(trace_id, 255),
                "tool_summary": bounded_text(tool_summary, 2000),
            }
            if feedback is None:
                feedback = ChatFeedback(
                    chainlit_feedback_id=bounded_feedback_id,
                    **values,
                )
                session.add(feedback)
            else:
                for key, value in values.items():
                    setattr(feedback, key, value)
            await self._commit(session)
            await session.refresh(feedback)
            return feedback

    async def delete_chainlit_feedback(self, feedback_id: str) -> bool:
        """Delete one feedback action by its stable Chainlit ID."""
        async with self._sessions() as session:
            result = await session.execute(
                delete(ChatFeedback).where(ChatFeedback.chainlit_feedback_id == feedback_id[:255])
            )
            await self._commit(session)
            return bool(getattr(result, "rowcount", 0))
