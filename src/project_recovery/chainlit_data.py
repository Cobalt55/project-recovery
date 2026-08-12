"""Application-owned Chainlit data layer over the durable chat repositories."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from chainlit.data.base import BaseDataLayer
from chainlit.data.utils import queue_until_user_message
from chainlit.element import Element, ElementDict
from chainlit.step import StepDict
from chainlit.types import (
    Feedback,
    PageInfo,
    PaginatedResponse,
    Pagination,
    ThreadDict,
    ThreadFilter,
)
from chainlit.user import PersistedUser
from chainlit.user import User as ChainlitUser

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_THREAD_PAGE = 50
MAX_THREAD_MESSAGES = 100
ROLE_BY_STEP_TYPE = {
    "user_message": "user",
    "assistant_message": "assistant",
    "system_message": "system",
}
STEP_TYPE_BY_ROLE = {
    "user": "user_message",
    "assistant": "assistant_message",
    "system": "system_message",
    "tool": "tool",
}


class ChainlitDataLayer(BaseDataLayer):
    """Keep Chainlit history private, durable, bounded, and user-owned."""

    def __init__(
        self,
        *,
        chats: Any,
        users: Any,
        attachment_root: str | Path,
        principal_provider: Callable[[], str | None],
        runtime: Any | None = None,
    ) -> None:
        self._chats = chats
        self._users = users
        self._attachment_root = Path(attachment_root).resolve()
        self._principal_provider = principal_provider
        self._runtime = runtime

    async def get_user(self, identifier: str) -> PersistedUser | None:
        user_id = _uuid(identifier)
        if user_id is None:
            return None
        user = await self._users.get(user_id)
        if user is None or not user.is_active:
            return None
        return PersistedUser(
            id=str(user.id),
            identifier=str(user.id),
            display_name=user.display_name,
            createdAt=user.created_at.isoformat(),
            metadata={"roles": list(user.roles)},
        )

    async def create_user(self, user: ChainlitUser) -> PersistedUser | None:
        """Return the pre-existing application user; Chainlit cannot create accounts."""
        return await self.get_user(user.identifier)

    async def delete_feedback(self, feedback_id: str) -> bool:
        principal = self._principal_uuid()
        if principal is None:
            return False
        return bool(await self._chats.delete_chainlit_feedback(feedback_id, principal))

    async def upsert_feedback(self, feedback: Feedback) -> str:
        thread_id = feedback.threadId
        if not thread_id:
            raise ValueError("feedback requires a thread")
        conversation = await self._owned_thread(thread_id)
        if conversation is None:
            raise PermissionError("thread is unavailable")
        message = await self._chats.get_message_by_chainlit_id(feedback.forId)
        if message is not None and message.conversation_id != conversation.id:
            raise PermissionError("message is unavailable")
        messages = await self._chats.list_messages(conversation.id, 0, MAX_THREAD_MESSAGES)
        feedback_id = feedback.id or str(uuid4())
        stored = await self._chats.upsert_chainlit_feedback(
            feedback_id=feedback_id,
            user_id=conversation.user_id,
            conversation_id=conversation.id,
            message_id=message.id if message is not None else None,
            rating=1 if feedback.value == 1 else -1,
            comment=feedback.comment,
            context_snapshot={
                "messages": [
                    {"role": item.role, "content": item.content} for item in list(messages)[-20:]
                ]
            },
            model=_setting(conversation.settings, "model"),
            trace_id=None,
            tool_summary=None,
        )
        return str(stored.chainlit_feedback_id)

    @queue_until_user_message()  # type: ignore[no-untyped-call,untyped-decorator]
    async def create_element(self, element: Element) -> None:
        await self._upsert_element(element)

    async def get_element(self, thread_id: str, element_id: str) -> ElementDict | None:
        conversation = await self._owned_thread(thread_id)
        if conversation is None:
            return None
        attachment = await self._chats.get_attachment_by_chainlit_id(conversation.id, element_id)
        if attachment is None:
            return None
        return cast(ElementDict, dict(attachment.metadata_json))

    @queue_until_user_message()  # type: ignore[no-untyped-call,untyped-decorator]
    async def delete_element(self, element_id: str, thread_id: str | None = None) -> None:
        if thread_id:
            conversation = await self._owned_thread(thread_id)
        else:
            attachment = await self._chats.get_attachment_by_chainlit_element_id(element_id)
            conversation = (
                await self._chats.get_thread(attachment.conversation_id)
                if attachment is not None
                else None
            )
            if conversation is not None and not self._is_owner(conversation.user_id):
                conversation = None
        if conversation is None:
            return
        stored_path = await self._chats.delete_chainlit_attachment(conversation.id, element_id)
        if stored_path:
            self._remove_owned_path(stored_path)

    @queue_until_user_message()  # type: ignore[no-untyped-call,untyped-decorator]
    async def create_step(self, step_dict: StepDict) -> None:
        await self._upsert_step(step_dict)

    @queue_until_user_message()  # type: ignore[no-untyped-call,untyped-decorator]
    async def update_step(self, step_dict: StepDict) -> None:
        await self._upsert_step(step_dict)

    @queue_until_user_message()  # type: ignore[no-untyped-call,untyped-decorator]
    async def delete_step(self, step_id: str) -> None:
        message = await self._chats.get_message_by_chainlit_id(step_id)
        if message is None:
            return
        conversation = await self._chats.get_thread(message.conversation_id)
        if conversation is None or not self._is_owner(conversation.user_id):
            return
        await self._chats.delete_chainlit_message(conversation.id, step_id)

    async def get_thread_author(self, thread_id: str) -> str:
        conversation = await self._chats.get_thread_by_chainlit_id(thread_id)
        return str(conversation.user_id) if conversation is not None else ""

    async def delete_thread(self, thread_id: str) -> None:
        conversation = await self._owned_thread(thread_id)
        if conversation is not None:
            attachments = await self._chats.list_attachments(
                conversation.id, 0, MAX_THREAD_MESSAGES
            )
            if self._runtime is not None:
                await self._runtime.delete_conversation(conversation.openai_conversation_id)
            await self._chats.delete_thread(conversation.id)
            for attachment in attachments:
                stored_path = attachment.metadata_json.get("path")
                if isinstance(stored_path, str):
                    self._remove_owned_path(stored_path)

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse[ThreadDict]:
        principal = self._principal_uuid()
        requested = _uuid(filters.userId)
        if principal is not None:
            if requested is not None and requested != principal:
                return _empty_page()
            user_id = principal
        elif requested is not None:
            user_id = requested
        else:
            return _empty_page()
        first = min(max(pagination.first, 1), MAX_THREAD_PAGE)
        offset = _cursor_offset(pagination.cursor)
        conversations = list(await self._chats.list_user_threads(user_id, offset, first + 1))
        if filters.search:
            needle = filters.search.strip().casefold()
            conversations = [
                item for item in conversations if needle in _thread_name(item).casefold()
            ]
        has_next = len(conversations) > first
        selected = conversations[:first]
        threads = [await self._thread_dict(item) for item in selected]
        return PaginatedResponse(
            pageInfo=PageInfo(
                hasNextPage=has_next,
                startCursor=str(offset) if selected else None,
                endCursor=str(offset + len(selected)) if selected else None,
            ),
            data=threads,
        )

    async def get_thread(self, thread_id: str) -> ThreadDict | None:
        conversation = await self._chats.get_thread_by_chainlit_id(thread_id)
        principal = self._principal_uuid()
        if conversation is not None and principal is not None and conversation.user_id != principal:
            conversation = None
        return await self._thread_dict(conversation) if conversation is not None else None

    async def update_thread(
        self,
        thread_id: str,
        name: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> None:
        conversation = await self._owned_thread(thread_id)
        if conversation is None:
            return
        if user_id is not None and _uuid(user_id) != conversation.user_id:
            raise PermissionError("thread owner cannot be changed")
        settings = dict(conversation.settings or {})
        chainlit = dict(settings.get("chainlit") or {})
        if name is not None:
            chainlit["name"] = name[:255]
        if metadata is not None:
            chat_settings = metadata.get("chat_settings")
            if isinstance(chat_settings, dict):
                model = chat_settings.get("Model")
                effort = chat_settings.get("Reasoning")
                if isinstance(model, str):
                    settings["model"] = model
                if isinstance(effort, str):
                    settings["reasoning_effort"] = effort
            chainlit["metadata"] = metadata
        if tags is not None:
            chainlit["tags"] = [str(tag)[:64] for tag in tags[:20]]
        settings["chainlit"] = chainlit
        await self._chats.update_thread_details(conversation.id, settings=settings)

    async def build_debug_url(self) -> str:
        return ""

    async def close(self) -> None:
        """The FastAPI lifespan owns the shared database engine."""
        return None

    async def get_favorite_steps(self, user_id: str) -> list[StepDict]:
        del user_id
        return []

    async def _upsert_step(self, step: StepDict) -> None:
        thread_id = step.get("threadId")
        step_id = step.get("id")
        if not thread_id or not step_id:
            return
        conversation = await self._owned_thread(thread_id)
        if conversation is None:
            raise PermissionError("thread is unavailable")
        step_type = str(step.get("type") or "tool")
        role = ROLE_BY_STEP_TYPE.get(step_type, "tool")
        content = str(step.get("output") or step.get("input") or "")
        await self._chats.upsert_chainlit_message(
            conversation_id=conversation.id,
            step_id=step_id,
            role=role,
            content=content,
        )

    async def _upsert_element(self, element: Element) -> None:
        thread_id = getattr(element, "thread_id", None)
        element_id = getattr(element, "id", None)
        if not thread_id or not element_id:
            return
        conversation = await self._owned_thread(thread_id)
        if conversation is None:
            raise PermissionError("thread is unavailable")
        message = None
        for_id = getattr(element, "for_id", None)
        if for_id:
            message = await self._chats.get_message_by_chainlit_id(for_id)
            if message is not None and message.conversation_id != conversation.id:
                raise PermissionError("message is unavailable")
        source = getattr(element, "path", None)
        durable_path: Path | None = None
        byte_size = 0
        if source:
            source_path = Path(source)
            byte_size = source_path.stat().st_size
            if byte_size > MAX_ATTACHMENT_BYTES:
                raise ValueError("attachment exceeds 25 MiB")
            durable_path = self._destination(conversation.id, element_id, element.name)
            durable_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, durable_path)
        else:
            content = getattr(element, "content", None)
            raw_content = content.encode("utf-8") if isinstance(content, str) else content
            if isinstance(raw_content, bytes):
                byte_size = len(raw_content)
                if byte_size > MAX_ATTACHMENT_BYTES:
                    raise ValueError("attachment exceeds 25 MiB")
                durable_path = self._destination(conversation.id, element_id, element.name)
                durable_path.parent.mkdir(parents=True, exist_ok=True)
                durable_path.write_bytes(raw_content)
        metadata = dict(element.to_dict())
        if durable_path is not None:
            metadata["path"] = str(durable_path)
        metadata.pop("content", None)
        await self._chats.upsert_chainlit_attachment(
            conversation_id=conversation.id,
            message_id=message.id if message is not None else None,
            element_id=element_id,
            filename=str(getattr(element, "name", "attachment"))[:255],
            content_type=str(getattr(element, "mime", None) or "application/octet-stream"),
            byte_size=byte_size,
            metadata=metadata,
        )

    async def _thread_dict(self, conversation: Any) -> ThreadDict:
        messages = await self._chats.list_messages(conversation.id, 0, MAX_THREAD_MESSAGES)
        attachments = await self._chats.list_attachments(conversation.id, 0, MAX_THREAD_MESSAGES)
        settings = dict(conversation.settings or {})
        chainlit = dict(settings.get("chainlit") or {})
        metadata = dict(chainlit.get("metadata") or {})
        metadata["chat_settings"] = {
            "Model": _setting(settings, "model") or "gpt-5.6-terra",
            "Reasoning": _setting(settings, "reasoning_effort") or "medium",
        }
        steps: list[StepDict] = [
            {
                "id": item.chainlit_step_id or str(item.id),
                "threadId": conversation.chainlit_thread_id,
                "name": item.role,
                "type": cast(Any, STEP_TYPE_BY_ROLE.get(item.role, "tool")),
                "input": "",
                "output": item.content,
                "metadata": {},
                "createdAt": item.created_at.isoformat(),
            }
            for item in messages
        ]
        elements = [cast(ElementDict, dict(item.metadata_json)) for item in attachments]
        return ThreadDict(
            id=conversation.chainlit_thread_id,
            createdAt=conversation.created_at.isoformat(),
            name=_thread_name(conversation),
            userId=str(conversation.user_id),
            userIdentifier=str(conversation.user_id),
            tags=list(chainlit.get("tags") or []),
            metadata=metadata,
            steps=steps,
            elements=elements,
        )

    async def _owned_thread(self, thread_id: str) -> Any | None:
        conversation = await self._chats.get_thread_by_chainlit_id(thread_id)
        if conversation is None or not self._is_owner(conversation.user_id):
            return None
        return conversation

    def _is_owner(self, user_id: UUID) -> bool:
        return self._principal_uuid() == user_id

    def _principal_uuid(self) -> UUID | None:
        return _uuid(self._principal_provider())

    def _destination(self, conversation_id: UUID, element_id: str, filename: str) -> Path:
        digest = hashlib.sha256(element_id.encode("utf-8")).hexdigest()
        suffix = Path(filename).suffix.casefold()[:16]
        return self._attachment_root / conversation_id.hex / f"{digest}{suffix}"

    def _remove_owned_path(self, stored_path: str) -> None:
        path = Path(stored_path).resolve()
        if path.is_relative_to(self._attachment_root):
            path.unlink(missing_ok=True)


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _setting(settings: object, key: str) -> str | None:
    if not isinstance(settings, dict):
        return None
    value = settings.get(key)
    return value if isinstance(value, str) else None


def _thread_name(conversation: Any) -> str:
    settings = conversation.settings if isinstance(conversation.settings, dict) else {}
    chainlit = settings.get("chainlit") if isinstance(settings.get("chainlit"), dict) else {}
    name = chainlit.get("name") if isinstance(chainlit, dict) else None
    return str(name or "New chat")[:255]


def _cursor_offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, min(int(cursor), 1_000_000))
    except ValueError:
        return 0


def _empty_page() -> PaginatedResponse[ThreadDict]:
    return PaginatedResponse(
        pageInfo=PageInfo(hasNextPage=False, startCursor=None, endCursor=None),
        data=[],
    )


__all__ = ["ChainlitDataLayer", "MAX_ATTACHMENT_BYTES"]
