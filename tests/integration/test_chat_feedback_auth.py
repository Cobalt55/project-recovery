"""Mounted Chainlit feedback requests must carry the live application principal."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from chainlit.auth import create_jwt
from chainlit.user import User as ChainlitUser
from fastapi.testclient import TestClient

from project_recovery.admin.shell import AppServices
from project_recovery.app import create_app
from project_recovery.auth.cookies import CHAINLIT_COOKIE_PREFIX, SESSION_COOKIE
from project_recovery.auth.sessions import CurrentUser
from project_recovery.chat_state import ChatDependencies
from project_recovery.config import Settings


class FeedbackAuth:
    def __init__(self, owner_id: UUID, other_id: UUID) -> None:
        self.owner = CurrentUser(owner_id, "owner@example.test", ("user",), False)
        self.other = CurrentUser(other_id, "other@example.test", ("user",), False)
        self.sessions = {"owner-session": self.owner, "other-session": self.other}

    async def current_user(self, token: str) -> CurrentUser | None:
        return self.sessions.get(token)


class FeedbackUsers:
    def __init__(self, owner_id: UUID, other_id: UUID) -> None:
        created_at = datetime(2026, 8, 13, tzinfo=UTC)
        self.users = {
            owner_id: SimpleNamespace(
                id=owner_id,
                display_name="Owner",
                roles=["user"],
                is_active=True,
                created_at=created_at,
            ),
            other_id: SimpleNamespace(
                id=other_id,
                display_name="Other",
                roles=["user"],
                is_active=True,
                created_at=created_at,
            ),
        }

    async def get(self, user_id: UUID) -> SimpleNamespace | None:
        return self.users.get(user_id)


class FeedbackChats:
    def __init__(self, owner_id: UUID, other_id: UUID) -> None:
        self.owner_id = owner_id
        self.other_id = other_id
        self.conversations = {
            "owner-thread": SimpleNamespace(
                id=uuid4(), user_id=owner_id, settings={"model": "gpt-5.6-terra"}
            ),
            "other-thread": SimpleNamespace(
                id=uuid4(), user_id=other_id, settings={"model": "gpt-5.6-terra"}
            ),
        }
        self.feedback_owners = {"owner-feedback": owner_id, "other-feedback": other_id}
        self.upserts: list[dict[str, object]] = []
        self.deletes: list[tuple[str, UUID]] = []

    async def get_thread_by_chainlit_id(self, thread_id: str) -> SimpleNamespace | None:
        return self.conversations.get(thread_id)

    async def get_message_by_chainlit_id(self, step_id: str) -> SimpleNamespace | None:
        thread_id = "owner-thread" if step_id == "owner-step" else "other-thread"
        conversation = self.conversations[thread_id]
        return SimpleNamespace(id=uuid4(), conversation_id=conversation.id)

    async def list_messages(self, conversation_id: UUID, offset: int, limit: int) -> list[object]:
        del conversation_id, offset, limit
        return []

    async def upsert_chainlit_feedback(self, **values: object) -> SimpleNamespace:
        self.upserts.append(values)
        feedback_id = str(values["feedback_id"])
        self.feedback_owners[feedback_id] = values["user_id"]  # type: ignore[assignment]
        return SimpleNamespace(chainlit_feedback_id=feedback_id)

    async def delete_chainlit_feedback(self, feedback_id: str, user_id: UUID) -> bool:
        self.deletes.append((feedback_id, user_id))
        if self.feedback_owners.get(feedback_id) != user_id:
            return False
        del self.feedback_owners[feedback_id]
        return True


class FakeDatabase:
    async def close(self) -> None:
        return None

    async def ping(self) -> bool:
        return True


def _settings() -> Settings:
    return Settings(
        openai_api_key="test-key",
        openai_vector_store_id="vs-test",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        app_session_secret="test-app-secret",
        chainlit_auth_secret="test-chainlit-secret",
        environment="test",
    )


@contextmanager
def feedback_client() -> tuple[TestClient, FeedbackAuth, FeedbackChats]:
    # Chainlit reuses one process-global FastAPI application for every mount.
    # TestClient builds its middleware stack, so allow the next isolated mount
    # to register its path-routing middleware just like a fresh process would.
    import chainlit.data as chainlit_data
    from chainlit.server import app as chainlit_server

    chainlit_server.middleware_stack = None
    chainlit_data._data_layer = None
    chainlit_data._data_layer_initialized = False
    owner_id, other_id = uuid4(), uuid4()
    auth = FeedbackAuth(owner_id, other_id)
    users = FeedbackUsers(owner_id, other_id)
    chats = FeedbackChats(owner_id, other_id)
    services = AppServices(
        database=FakeDatabase(),
        auth=auth,  # type: ignore[arg-type]
        users=users,  # type: ignore[arg-type]
        chat=ChatDependencies(
            auth=auth,
            users=users,
            chats=chats,
            runtime=SimpleNamespace(),
            attachment_root=Path("uploads"),
        ),
    )
    try:
        with TestClient(create_app(_settings(), services), follow_redirects=False) as client:
            yield client, auth, chats
    finally:
        chainlit_server.middleware_stack = None
        chainlit_data._data_layer = None
        chainlit_data._data_layer_initialized = False


def _authenticate(client: TestClient, current: CurrentUser, token: str) -> None:
    client.cookies.set(SESSION_COOKIE, token)
    client.cookies.set(
        CHAINLIT_COOKIE_PREFIX,
        create_jwt(ChainlitUser(identifier=str(current.user_id), display_name=current.email)),
    )


def test_put_feedback_uses_the_live_application_principal() -> None:
    """Removing the HTTP principal handoff makes Chainlit reject an owner's feedback."""
    with feedback_client() as (client, auth, chats):
        _authenticate(client, auth.owner, "owner-session")

        response = client.put(
            "/chat/feedback",
            json={
                "feedback": {
                    "id": "new-owner-feedback",
                    "forId": "owner-step",
                    "threadId": "owner-thread",
                    "value": 1,
                    "comment": "Helpful",
                },
                "sessionId": "http-feedback-session",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"success": True, "feedbackId": "new-owner-feedback"}
    assert chats.upserts[0]["user_id"] == auth.owner.user_id


def test_delete_feedback_uses_the_live_application_principal() -> None:
    """Removing the HTTP principal handoff leaves Chainlit reporting a false delete success."""
    with feedback_client() as (client, auth, chats):
        _authenticate(client, auth.owner, "owner-session")

        response = client.request("DELETE", "/chat/feedback", json={"feedbackId": "owner-feedback"})

    assert response.status_code == 200
    assert "owner-feedback" not in chats.feedback_owners
    assert chats.deletes == [("owner-feedback", auth.owner.user_id)]


def test_feedback_rejects_an_active_session_bound_to_a_different_chainlit_identity() -> None:
    """A swapped Chainlit JWT must not borrow another live application session."""
    with feedback_client() as (client, auth, chats):
        _authenticate(client, auth.other, "owner-session")

        response = client.put(
            "/chat/feedback",
            json={
                "feedback": {
                    "id": "mismatched-feedback",
                    "forId": "owner-step",
                    "threadId": "owner-thread",
                    "value": 1,
                },
                "sessionId": "http-feedback-session",
            },
        )

    assert response.status_code == 401
    assert chats.upserts == []


@pytest.mark.parametrize("session_token", ["", "revoked-session"])
def test_feedback_rejects_missing_or_revoked_application_sessions(session_token: str) -> None:
    """A signed Chainlit JWT cannot authorize feedback after its opaque session is gone."""
    with feedback_client() as (client, auth, chats):
        if session_token:
            client.cookies.set(SESSION_COOKIE, session_token)
        client.cookies.set(
            CHAINLIT_COOKIE_PREFIX,
            create_jwt(
                ChainlitUser(identifier=str(auth.owner.user_id), display_name=auth.owner.email)
            ),
        )

        response = client.request("DELETE", "/chat/feedback", json={"feedbackId": "owner-feedback"})

    assert response.status_code == 401
    assert chats.feedback_owners["owner-feedback"] == auth.owner.user_id
    assert chats.deletes == []


def test_feedback_cannot_write_or_delete_another_users_records() -> None:
    """Changing requested feedback identifiers must not cross the durable owner boundary."""
    with feedback_client() as (client, auth, chats):
        _authenticate(client, auth.owner, "owner-session")

        update = client.put(
            "/chat/feedback",
            json={
                "feedback": {
                    "id": "other-feedback",
                    "forId": "other-step",
                    "threadId": "other-thread",
                    "value": 0,
                },
                "sessionId": "http-feedback-session",
            },
        )
        deletion = client.request("DELETE", "/chat/feedback", json={"feedbackId": "other-feedback"})

    assert update.status_code == 500
    assert deletion.status_code == 200
    assert chats.upserts == []
    assert chats.feedback_owners["other-feedback"] == auth.other.user_id
    assert chats.deletes[-1] == ("other-feedback", auth.owner.user_id)
