"""Contract tests for the application-owned Chainlit persistence adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from chainlit.data.base import BaseDataLayer
from chainlit.types import Feedback, Pagination, ThreadFilter
from chainlit.user import User as ChainlitUser

from project_recovery.chainlit_data import ChainlitDataLayer


class FakeUsers:
    def __init__(self, user: SimpleNamespace) -> None:
        self.user = user

    async def get(self, user_id: object) -> SimpleNamespace | None:
        return self.user if str(user_id) == str(self.user.id) else None


class FakeChats:
    def __init__(self, conversation: SimpleNamespace) -> None:
        self.conversation = conversation
        self.messages: list[SimpleNamespace] = []
        self.attachments: list[SimpleNamespace] = []
        self.feedback_calls: list[dict[str, object]] = []
        self.step_calls: list[dict[str, object]] = []

    async def get_thread_by_chainlit_id(self, thread_id: str) -> SimpleNamespace | None:
        return self.conversation if thread_id == self.conversation.chainlit_thread_id else None

    async def list_user_threads(
        self, user_id: object, offset: int, limit: int
    ) -> list[SimpleNamespace]:
        del offset, limit
        return [self.conversation] if str(user_id) == str(self.conversation.user_id) else []

    async def list_messages(
        self, conversation_id: object, offset: int, limit: int
    ) -> list[SimpleNamespace]:
        del offset, limit
        return self.messages if conversation_id == self.conversation.id else []

    async def list_attachments(
        self, conversation_id: object, offset: int, limit: int
    ) -> list[SimpleNamespace]:
        del offset, limit
        return self.attachments if conversation_id == self.conversation.id else []

    async def update_thread_details(self, conversation_id: object, **values: object) -> None:
        assert conversation_id == self.conversation.id
        self.conversation.settings = values["settings"]

    async def upsert_chainlit_message(self, **values: object) -> SimpleNamespace:
        self.step_calls.append(values)
        return SimpleNamespace(id=uuid4(), **values)

    async def delete_chainlit_message(self, conversation_id: object, step_id: str) -> bool:
        return conversation_id == self.conversation.id and step_id == "step-1"

    async def get_message_by_chainlit_id(self, step_id: str) -> SimpleNamespace | None:
        return (
            SimpleNamespace(id=uuid4(), conversation_id=self.conversation.id)
            if step_id == "step-1"
            else None
        )

    async def upsert_chainlit_attachment(self, **values: object) -> SimpleNamespace:
        attachment = SimpleNamespace(
            id=uuid4(),
            chainlit_element_id=values["element_id"],
            metadata_json=values["metadata"],
            **values,
        )
        self.attachments = [attachment]
        return attachment

    async def get_attachment_by_chainlit_id(
        self, conversation_id: object, element_id: str
    ) -> SimpleNamespace | None:
        for attachment in self.attachments:
            if (
                attachment.conversation_id == conversation_id
                and attachment.chainlit_element_id == element_id
            ):
                return attachment
        return None

    async def get_attachment_by_chainlit_element_id(
        self, element_id: str
    ) -> SimpleNamespace | None:
        for attachment in self.attachments:
            if attachment.chainlit_element_id == element_id:
                return attachment
        return None

    async def get_thread(self, conversation_id: object) -> SimpleNamespace | None:
        return self.conversation if conversation_id == self.conversation.id else None

    async def delete_chainlit_attachment(
        self, conversation_id: object, element_id: str
    ) -> str | None:
        attachment = await self.get_attachment_by_chainlit_id(conversation_id, element_id)
        return attachment.metadata_json.get("path") if attachment else None

    async def upsert_chainlit_feedback(self, **values: object) -> SimpleNamespace:
        self.feedback_calls.append(values)
        return SimpleNamespace(id=uuid4(), chainlit_feedback_id=values["feedback_id"])

    async def delete_chainlit_feedback(self, feedback_id: str) -> bool:
        return feedback_id == "feedback-1"

    async def delete_thread(self, conversation_id: object) -> bool:
        return conversation_id == self.conversation.id


def _layer(tmp_path: Path, *, owner: bool = True) -> tuple[ChainlitDataLayer, FakeChats]:
    user_id = uuid4()
    principal_id = str(user_id if owner else uuid4())
    user = SimpleNamespace(
        id=user_id,
        email="operator@example.test",
        display_name="Operator",
        roles=["admin"],
        is_active=True,
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    conversation = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        chainlit_thread_id="thread-1",
        settings={
            "model": "gpt-5.6-terra",
            "reasoning_effort": "medium",
            "chainlit": {"name": "A calm thread", "tags": ["saved"], "metadata": {}},
        },
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        updated_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    chats = FakeChats(conversation)
    layer = ChainlitDataLayer(
        chats=chats,
        users=FakeUsers(user),
        attachment_root=tmp_path,
        principal_provider=lambda: principal_id,
    )
    return layer, chats


def test_adapter_implements_every_chainlit_data_layer_method(tmp_path: Path) -> None:
    layer, _ = _layer(tmp_path)

    assert isinstance(layer, BaseDataLayer)
    assert not layer.__class__.__abstractmethods__
    for method_name in (
        "create_element",
        "delete_element",
        "create_step",
        "update_step",
        "delete_step",
    ):
        assert hasattr(getattr(layer, method_name), "__wrapped__")


@pytest.mark.asyncio
async def test_user_threads_and_steps_are_owned_bounded_and_resumable(tmp_path: Path) -> None:
    layer, chats = _layer(tmp_path)
    chats.messages.append(
        SimpleNamespace(
            id=uuid4(),
            chainlit_step_id="step-1",
            role="assistant",
            content="A durable answer",
            created_at=datetime(2026, 8, 12, tzinfo=UTC),
        )
    )

    user = await layer.get_user(str(chats.conversation.user_id))
    created = await layer.create_user(ChainlitUser(identifier=str(chats.conversation.user_id)))
    page = await layer.list_threads(
        Pagination(first=25),
        ThreadFilter(userId=str(chats.conversation.user_id)),
    )
    thread = await layer.get_thread("thread-1")

    assert user is not None and created == user
    assert len(page.data) == 1
    assert page.pageInfo.hasNextPage is False
    assert thread is not None
    assert thread["userIdentifier"] == str(chats.conversation.user_id)
    assert thread["metadata"]["chat_settings"] == {
        "Model": "gpt-5.6-terra",
        "Reasoning": "medium",
    }
    assert thread["steps"][0]["id"] == "step-1"
    assert thread["steps"][0]["output"] == "A durable answer"


@pytest.mark.asyncio
async def test_cross_user_thread_access_is_rejected(tmp_path: Path) -> None:
    layer, chats = _layer(tmp_path, owner=False)

    assert await layer.get_thread("thread-1") is None
    page = await layer.list_threads(
        Pagination(first=25),
        ThreadFilter(userId=str(chats.conversation.user_id)),
    )
    assert page.data == []


@pytest.mark.asyncio
async def test_steps_elements_and_feedback_use_application_records(tmp_path: Path) -> None:
    layer, chats = _layer(tmp_path)
    await layer.create_step.__wrapped__(
        layer,
        {
            "id": "step-1",
            "threadId": "thread-1",
            "type": "assistant_message",
            "name": "assistant",
            "output": "Saved once",
            "metadata": {},
        },
    )
    await layer.update_step.__wrapped__(
        layer,
        {
            "id": "step-1",
            "threadId": "thread-1",
            "type": "assistant_message",
            "name": "assistant",
            "output": "Updated, not duplicated",
            "metadata": {},
        },
    )

    source = tmp_path / "incoming.txt"
    source.write_text("private attachment", encoding="utf-8")
    element = SimpleNamespace(
        id="element-1",
        thread_id="thread-1",
        for_id="step-1",
        name="note.txt",
        mime="text/plain",
        path=str(source),
        to_dict=lambda: {
            "id": "element-1",
            "threadId": "thread-1",
            "forId": "step-1",
            "name": "note.txt",
            "mime": "text/plain",
            "type": "file",
            "display": "side",
        },
    )
    await layer.create_element.__wrapped__(layer, element)
    stored_path = Path(chats.attachments[0].metadata_json["path"])
    feedback_id = await layer.upsert_feedback(
        Feedback(
            id="feedback-1",
            forId="step-1",
            threadId="thread-1",
            value=1,
            comment="Helpful",
        )
    )

    assert [call["content"] for call in chats.step_calls] == [
        "Saved once",
        "Updated, not duplicated",
    ]
    assert stored_path != source and stored_path.read_text(encoding="utf-8") == "private attachment"
    assert feedback_id == "feedback-1"
    assert chats.feedback_calls[0]["rating"] == 1
    assert await layer.delete_feedback("feedback-1") is True

    await layer.upsert_feedback(
        Feedback(
            id="feedback-2",
            forId="step-1",
            threadId="thread-1",
            value=0,
        )
    )
    assert chats.feedback_calls[-1]["rating"] == -1

    await layer.delete_element.__wrapped__(layer, "element-1")
    assert not stored_path.exists()
