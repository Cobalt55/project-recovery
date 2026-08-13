"""Integration-shaped checks for the generic Chainlit chat boundary."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

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


def make_request(cookie: str) -> Request:
    return Request({"type": "http", "headers": [(b"cookie", cookie.encode())]})


def assert_cookie_deleted(set_cookie: list[str], name: str) -> None:
    assert any(
        header.startswith(f"{name}=") and "Max-Age=0" in header for header in set_cookie
    )


@pytest.mark.asyncio
async def test_chainlit_logout_revokes_application_session_and_clears_all_auth_cookies() -> None:
    """Removing callback logout or a cookie deletion must leave a live credential behind."""

    class FakeAuth:
        def __init__(self) -> None:
            self.logged_out: list[str] = []

        async def logout(self, token: str) -> None:
            self.logged_out.append(token)

    auth = FakeAuth()
    configure_chat(
        ChatDependencies(
            auth=auth,
            users=SimpleNamespace(),
            chats=SimpleNamespace(),
            runtime=SimpleNamespace(),
            attachment_root=Path("uploads"),
        )
    )
    request = make_request(
        "project_recovery_session=active-token; "
        "project_recovery_csrf=csrf-token; access_token=jwt"
    )
    response = Response()

    await chat_app.on_logout(request, response)

    assert auth.logged_out == ["active-token"]
    set_cookie = response.headers.getlist("set-cookie")
    assert_cookie_deleted(set_cookie, "project_recovery_session")
    assert_cookie_deleted(set_cookie, "project_recovery_csrf")
    assert_cookie_deleted(set_cookie, "access_token")


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


def test_chainlit_workspace_contract_uses_the_approved_native_shell_hooks() -> None:
    """The visual shim stays attached to stable Chainlit IDs instead of generated classes."""

    root = Path(__file__).parents[2]
    config = (root / ".chainlit" / "config.toml").read_text(encoding="utf-8")
    translations = (root / ".chainlit" / "translations" / "en-US.json").read_text(
        encoding="utf-8"
    )
    stylesheet = (root / "public" / "chat-navigation.css").read_text(encoding="utf-8")
    navigation = (root / "public" / "chat-navigation.js").read_text(encoding="utf-8")

    assert 'name = "Project Recovery"' in config
    assert "Ask a grounded question" in translations
    assert "Project Recovery" in navigation
    nav_rule = stylesheet.split("#project-recovery-nav", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "bottom:" not in nav_rule
    assert "#project-recovery-nav" in stylesheet
    assert "#chat-submit" in navigation
    assert "#upload-button" in navigation
    assert "#chat-settings-open-modal" in navigation
    assert "MutationObserver" in navigation
    assert "function enhance(root)" in navigation
    assert "data-pr-enhanced" in navigation
    assert "data-pr-drawer-open" in navigation
    assert "data-pr-drawer-close" in navigation
    assert "Send message" in navigation
    assert "Stop response" in navigation
    assert '"stop": "Stop response"' in translations


def test_chainlit_empty_chat_uses_the_project_recovery_identity_asset() -> None:
    """A default Chainlit wordmark in the empty workspace is a visible identity regression."""
    root = Path(__file__).parents[2]
    logo = root / "public" / "logo_light.svg"

    assert logo.is_file()
    assert "Project Recovery" in logo.read_text(encoding="utf-8")


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
    assert auth_config.json()["passwordAuth"] is False
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

    class ActiveAuth:
        async def current_user(self, candidate: object) -> SimpleNamespace | None:
            if candidate != "active-token":
                return None
            return SimpleNamespace(
                user_id=user_id,
                force_password_change=False,
            )

    configure_chat(
        ChatDependencies(
            auth=ActiveAuth(),
            users=users,
            chats=SimpleNamespace(),
            runtime=runtime,
            attachment_root=Path("uploads"),
        )
    )
    monkeypatch.setattr(chat_app.cl, "user_session", FakeSession())
    monkeypatch.setattr(
        chat_app.cl,
        "context",
        SimpleNamespace(
            session=SimpleNamespace(
                environ={"HTTP_COOKIE": "project_recovery_session=active-token"}
            )
        ),
    )
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

    class ActiveAuth:
        async def current_user(self, candidate: object) -> SimpleNamespace | None:
            if candidate != "active-token":
                return None
            return SimpleNamespace(
                user_id=user_id,
                force_password_change=False,
            )

    configure_chat(
        ChatDependencies(
            auth=ActiveAuth(),
            users=InactiveUsers(),
            chats=SimpleNamespace(),
            runtime=runtime,
            attachment_root=Path("uploads"),
        )
    )
    monkeypatch.setattr(chat_app.cl, "user_session", FakeSession())
    monkeypatch.setattr(
        chat_app.cl,
        "context",
        SimpleNamespace(
            session=SimpleNamespace(
                environ={"HTTP_COOKIE": "project_recovery_session=active-token"}
            )
        ),
    )

    class UnexpectedMessage:
        def __init__(self, content: str = "") -> None:
            self.content = content

        async def update(self) -> None:
            return None

    monkeypatch.setattr(chat_app.cl, "Message", UnexpectedMessage)

    with pytest.raises(PermissionError, match="authentication"):
        await chat_app.on_message(SimpleNamespace(content="Question"))


@pytest.mark.asyncio
async def test_cached_chat_rejects_an_explicitly_revoked_application_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A signed Chainlit JWT cannot outlive its backing login session."""
    user_id = uuid4()
    conversation = SimpleNamespace(id=uuid4(), user_id=user_id)

    class FakeSession:
        def get(self, key: str, default: object = None) -> object:
            return {
                "user": chat_app.ChainlitUser(identifier=str(user_id)),
                "conversation": conversation,
            }.get(key, default)

    class RevokedAuth:
        def __init__(self) -> None:
            self.calls: list[object] = []

        async def current_user(self, candidate: object) -> None:
            self.calls.append(candidate)
            return None

    class ActiveUsers:
        async def get(self, candidate: object) -> SimpleNamespace:
            assert candidate == user_id
            return SimpleNamespace(id=user_id, is_active=True, force_password_change=False)

    auth = RevokedAuth()
    configure_chat(
        ChatDependencies(
            auth=auth,
            users=ActiveUsers(),
            chats=SimpleNamespace(),
            runtime=SimpleNamespace(),
            attachment_root=Path("uploads"),
        )
    )
    monkeypatch.setattr(chat_app.cl, "user_session", FakeSession())
    monkeypatch.setattr(
        chat_app.cl,
        "context",
        SimpleNamespace(
            session=SimpleNamespace(
                environ={"HTTP_COOKIE": "project_recovery_session=revoked-token"}
            )
        ),
    )

    with pytest.raises(PermissionError, match="authentication"):
        await chat_app._revalidated_conversation()
    assert auth.calls == ["revoked-token"]
