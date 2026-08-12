"""Integration-shaped checks for the generic Chainlit chat boundary."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import project_recovery.chat_app as chat_app
from project_recovery.agent_runtime import AgentEvent
from project_recovery.app import create_app
from project_recovery.chat_app import (
    MODEL_WIDGET_ID,
    REASONING_WIDGET_ID,
    validate_chat_settings,
)
from project_recovery.chat_state import ChatDependencies, configure_chat
from project_recovery.config import Settings


def test_chat_settings_expose_only_the_approved_policy() -> None:
    assert validate_chat_settings(
        {
            MODEL_WIDGET_ID: "gpt-5.6-terra",
            REASONING_WIDGET_ID: "medium",
        }
    ) == ("gpt-5.6-terra", "medium")
    assert (
        validate_chat_settings(
            {
                MODEL_WIDGET_ID: "gpt-4o",
                REASONING_WIDGET_ID: "medium",
            }
        )
        is None
    )


def test_chainlit_configuration_is_private_bounded_and_generic() -> None:
    root = Path(__file__).parents[2]
    config = (root / ".chainlit" / "config.toml").read_text(encoding="utf-8")
    navigation = (root / "public" / "chat-navigation.js").read_text(encoding="utf-8")

    assert "max_size_mb = 25" in config
    assert "/public/chat-navigation.css" in config
    assert "/public/chat-navigation.js" in config
    assert "/settings" in navigation
    combined = (config + navigation).casefold()
    for forbidden in ("salesforce", "myclubhub", "bgcmd", "school harbor"):
        assert forbidden not in combined


def test_chainlit_mount_uses_authenticated_callbacks_and_custom_navigation() -> None:
    settings = Settings(
        openai_api_key="sk-test",
        openai_vector_store_id="vs-test",
        database_url="postgresql+asyncpg://user:password@127.0.0.1:9/test",
        app_session_secret="application-test-secret",
        chainlit_auth_secret="chainlit-test-secret",
        environment="test",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        auth_config = client.get("/chat/auth/config")
        navigation = client.get("/chat/public/chat-navigation.js")

    assert auth_config.status_code == 200
    assert auth_config.json()["requireLogin"] is True
    assert auth_config.json()["headerAuth"] is True
    assert auth_config.json()["passwordAuth"] is True
    assert navigation.status_code == 200
    assert "/settings" in navigation.text


@pytest.mark.asyncio
async def test_message_callback_streams_runtime_without_duplicate_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    conversation = SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        openai_conversation_id="conv-test",
        settings={"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
    )

    class FakeSession:
        def __init__(self) -> None:
            self.values = {
                "user": chat_app.ChainlitUser(identifier=str(user_id)),
                "conversation": conversation,
                MODEL_WIDGET_ID: "gpt-5.6-terra",
                REASONING_WIDGET_ID: "medium",
            }

        def get(self, key: str, default: object = None) -> object:
            return self.values.get(key, default)

        def set(self, key: str, value: object) -> None:
            self.values[key] = value

    messages: list[object] = []

    class FakeMessage:
        def __init__(self, content: str = "", **kwargs: object) -> None:
            del kwargs
            self.content = content
            messages.append(self)

        async def stream_token(self, token: str) -> None:
            self.content += token

        async def update(self) -> None:
            return None

        async def send(self) -> None:
            return None

    class FakeRuntime:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def stream_turn(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append(kwargs)
            emit = kwargs["emit"]
            await emit(AgentEvent(kind="text_delta", delta="Grounded answer"))
            await emit(
                AgentEvent(
                    kind="tool",
                    data={
                        "files": [
                            {
                                "file_id": "file-1",
                                "filename": "guide.pdf",
                                "score": 0.9,
                            }
                        ]
                    },
                )
            )
            return SimpleNamespace(final_output="Grounded answer")

    runtime = FakeRuntime()

    class ActiveUsers:
        async def get(self, candidate: object) -> SimpleNamespace | None:
            if candidate != user_id:
                return None
            return SimpleNamespace(id=user_id, is_active=True, force_password_change=False)

    users = ActiveUsers()
    configure_chat(
        ChatDependencies(
            auth=SimpleNamespace(),
            users=users,
            chats=SimpleNamespace(),
            runtime=runtime,
            attachment_root=Path("uploads"),
        )
    )
    monkeypatch.setattr(chat_app.cl, "user_session", FakeSession())
    monkeypatch.setattr(chat_app.cl, "Message", FakeMessage)

    await chat_app.on_message(SimpleNamespace(content="Question"))

    assert runtime.calls[0]["persist_messages"] is False
    assert messages[0].content == "Grounded answer\n\nSources: guide.pdf"


@pytest.mark.asyncio
async def test_message_callback_revalidates_cached_user_before_each_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deactivated user cannot continue through an already-open Chainlit session."""
    user_id = uuid4()
    conversation = SimpleNamespace(id=uuid4(), user_id=user_id)

    class FakeSession:
        def get(self, key: str, default: object = None) -> object:
            return {
                "user": chat_app.ChainlitUser(identifier=str(user_id)),
                "conversation": conversation,
                MODEL_WIDGET_ID: "gpt-5.6-terra",
                REASONING_WIDGET_ID: "medium",
            }.get(key, default)

    class InactiveUsers:
        async def get(self, candidate: object) -> SimpleNamespace | None:
            assert candidate == user_id
            return SimpleNamespace(id=user_id, is_active=False, force_password_change=False)

    runtime = SimpleNamespace(calls=[])
    configure_chat(
        ChatDependencies(
            auth=SimpleNamespace(),
            users=InactiveUsers(),
            chats=SimpleNamespace(),
            runtime=runtime,
            attachment_root=Path("uploads"),
        )
    )
    monkeypatch.setattr(chat_app.cl, "user_session", FakeSession())

    class UnexpectedMessage:
        def __init__(self, content: str = "") -> None:
            self.content = content

        async def update(self) -> None:
            return None

    monkeypatch.setattr(chat_app.cl, "Message", UnexpectedMessage)

    with pytest.raises(PermissionError, match="authentication"):
        await chat_app.on_message(SimpleNamespace(content="Question"))
