"""FastAPI route access and safety coverage without a live database dependency."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from project_recovery.admin.shell import AppServices
from project_recovery.app import create_app
from project_recovery.auth.sessions import CurrentUser, LoginResult
from project_recovery.chat_state import ChatDependencies
from project_recovery.config import Settings


class FakeAuth:
    """In-memory auth boundary that keeps route assertions independent of PostgreSQL."""

    def __init__(self) -> None:
        self.users = {
            "member@example.test": CurrentUser(uuid4(), "member@example.test", ("user",), False),
            "admin@example.test": CurrentUser(uuid4(), "admin@example.test", ("admin",), False),
            "forced@example.test": CurrentUser(uuid4(), "forced@example.test", ("user",), True),
        }
        self.sessions: dict[str, CurrentUser] = {}
        self.csrf = "test-csrf-value"

    async def login(self, email: str, password: str) -> LoginResult | None:
        user = self.users.get(email)
        if user is None or password != "correct horse battery staple":
            return None
        token = f"session-{email}"
        self.sessions[token] = user
        return LoginResult(uuid4(), token, self.csrf)

    async def current_user(self, token: str) -> CurrentUser | None:
        return self.sessions.get(token)

    async def validate_csrf(self, token: str, value: str) -> bool:
        return token in self.sessions and value == self.csrf

    async def logout(self, token: str) -> None:
        self.sessions.pop(token, None)

    async def change_password(self, token: str, current: str, new: str) -> bool:
        if token not in self.sessions or current != "correct horse battery staple" or len(new) < 20:
            return False
        self.sessions.clear()
        return True


class FakeUsers:
    """Route-level persistence double with bounded rows and visible write outcomes."""

    def __init__(self, auth: FakeAuth) -> None:
        self.auth = auth
        self.saved_settings: dict[UUID, dict[str, str]] = {}
        self.admin_id = auth.users["admin@example.test"].user_id
        self.member_id = auth.users["member@example.test"].user_id
        self.rows = [
            SimpleNamespace(
                id=self.admin_id,
                email="admin@example.test",
                display_name="Admin",
                roles=["admin"],
                is_active=True,
                force_password_change=False,
                created_at=datetime.now(UTC),
                last_login_at=datetime.now(UTC),
            ),
            SimpleNamespace(
                id=self.member_id,
                email="member@example.test",
                display_name="Member",
                roles=["user"],
                is_active=True,
                force_password_change=False,
                created_at=datetime.now(UTC),
                last_login_at=None,
            ),
        ]
        self.login_id = uuid4()
        self.login_rows = [
            SimpleNamespace(
                id=self.login_id,
                user_id=self.member_id,
                email="member@example.test",
                is_active=True,
                created_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(hours=12),
                revoked_at=None,
            )
        ]
        self.audit_events: list[tuple[str, UUID, dict[str, str]]] = []

    async def get_settings(self, user_id: UUID) -> dict[str, str]:
        return self.saved_settings.get(user_id, {})

    async def save_settings(self, user_id: UUID, settings: dict[str, str]) -> dict[str, str]:
        self.saved_settings[user_id] = settings
        return settings

    async def list_page(self, query: str | None, status: str | None, offset: int, limit: int):
        return self.rows[offset : offset + min(limit, 100)]

    async def list_logins(self, offset: int, limit: int):
        return self.login_rows[offset : offset + min(limit, 100)]

    async def create_user(
        self, actor_id: UUID, email: str, display_name: str, roles: list[str]
    ) -> str:
        return "temporary-password-shown-once"

    async def reset_password(self, actor_id: UUID, user_id: UUID) -> str:
        return "temporary-password-shown-once"

    async def set_active(self, actor_id: UUID, user_id: UUID, is_active: bool) -> None:
        for row in self.rows:
            if row.id == user_id:
                row.is_active = is_active

    async def set_roles(self, actor_id: UUID, user_id: UUID, roles: list[str]) -> None:
        for row in self.rows:
            if row.id == user_id:
                row.roles = roles
                self.audit_events.append(("roles_changed", user_id, {"roles": ",".join(roles)}))

    async def revoke_login(self, actor_id: UUID, login_id: UUID) -> bool:
        for login in self.login_rows:
            if login.id == login_id and login.revoked_at is None:
                login.revoked_at = datetime.now(UTC)
                self.audit_events.append(
                    ("login_revoked", login.user_id, {"session_id": str(login_id)})
                )
                return True
        return False


class FakeDatabase:
    async def ping(self) -> bool:
        return True

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        yield None

    async def close(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        openai_api_key="test-key",
        openai_vector_store_id="vs_test",
        database_url="postgresql+asyncpg://test:test@localhost/test",
        app_session_secret="session-secret",
        chainlit_auth_secret="chainlit-secret",
    )


def _client() -> tuple[TestClient, FakeAuth, FakeUsers]:
    auth = FakeAuth()
    users = FakeUsers(auth)
    app = create_app(_settings(), AppServices(database=FakeDatabase(), auth=auth, users=users))
    return TestClient(app, follow_redirects=False), auth, users


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 303


def test_anonymous_requests_redirect_to_login_and_health_is_sanitized() -> None:
    """Removing auth guards or adding settings to readiness must fail route-level behavior."""
    client, _, _ = _client()

    protected = client.get("/settings")
    ready = client.get("/health/ready")

    assert protected.status_code == 303
    assert protected.headers["location"] == "/login"
    assert ready.status_code == 200
    assert set(ready.json()) == {"database", "application", "correlation_id"}
    assert all("postgresql" not in str(value) for value in ready.json().values())
    assert ready.headers["cache-control"] == "no-store"


def test_repeated_login_failures_are_throttled_before_more_password_work() -> None:
    """The public login boundary limits normalized-account guessing."""
    client, _, _ = _client()

    for _ in range(5):
        response = client.post(
            "/login",
            data={"email": "missing@example.test", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked = client.post(
        "/login",
        data={"email": " MISSING@example.test ", "password": "wrong-password"},
    )
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "900"
    assert "We could not sign you in" in blocked.text


def test_member_navigation_and_settings_write_require_csrf() -> None:
    """An admin link leak, missing CSRF check, or skipped settings persistence must fail."""
    client, _, users = _client()
    _login(client, "member@example.test")

    page = client.get("/settings")
    forbidden = client.get("/admin/users")
    csrf_failure = client.post("/settings", data={"model": "gpt-5.6-terra"})
    saved = client.post(
        "/settings",
        data={
            "csrf_token": "test-csrf-value",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "theme": "system",
        },
    )

    assert page.status_code == 200
    assert "Users" not in page.text
    assert forbidden.status_code == 403
    assert csrf_failure.status_code == 403
    assert saved.status_code == 303
    assert users.saved_settings[users.member_id] == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "theme": "system",
    }


def test_application_login_also_establishes_the_chainlit_session() -> None:
    """A normal workspace login opens Chat without a second sign-in prompt."""
    client, _, _ = _client()

    _login(client, "admin@example.test")

    assert "access_token" in client.cookies


def test_chainlit_history_http_requires_a_live_application_session() -> None:
    """A stale Chainlit JWT cannot outlive logout or explicit session revocation."""
    client, auth, _ = _client()
    _login(client, "admin@example.test")

    live = client.post(
        "/chat/project/threads",
        json={"pagination": {"first": 10}, "filter": {}},
    )
    assert client.cookies.get("project_recovery_session") is not None
    auth.sessions.clear()
    revoked = client.post(
        "/chat/project/threads",
        json={"pagination": {"first": 10}, "filter": {}},
    )

    assert live.status_code != 401
    assert revoked.status_code == 401


def test_chainlit_logout_revokes_the_browser_session_across_workspace_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping Chainlit logout must not leave HTML or project endpoints authenticated."""
    from chainlit.server import app as chainlit_server

    monkeypatch.setattr(chainlit_server, "middleware_stack", None)
    auth = FakeAuth()
    users = FakeUsers(auth)
    services = AppServices(
        database=FakeDatabase(),
        auth=auth,
        users=users,
        chat=ChatDependencies(
            auth=auth,
            users=users,
            chats=SimpleNamespace(),
            runtime=SimpleNamespace(),
            attachment_root=Path("uploads"),
        ),
    )
    client = TestClient(create_app(_settings(), services), follow_redirects=False)
    _login(client, "admin@example.test")

    logout = client.post("/chat/logout")
    settings = client.get("/settings")
    logins = client.get("/admin/logins")
    threads = client.post(
        "/chat/project/threads",
        json={"pagination": {"first": 10}, "filter": {}},
    )

    assert logout.status_code == 200
    assert settings.status_code == 303
    assert settings.headers["location"] == "/login"
    assert logins.status_code == 303
    assert logins.headers["location"] == "/login"
    assert threads.status_code == 401


def test_admin_user_actions_and_login_table_keep_secrets_out_of_html() -> None:
    """Missing admin CSRF enforcement or token exposure must fail this observable boundary."""
    client, _, users = _client()
    _login(client, "admin@example.test")

    users_page = client.get("/admin/users?limit=999")
    logins_page = client.get("/admin/logins?limit=999")
    created = client.post(
        "/admin/users",
        data={
            "csrf_token": "test-csrf-value",
            "email": "new@example.test",
            "display_name": "New User",
            "roles": "user",
        },
    )
    deactivated = client.post(
        f"/admin/users/{users.member_id}/active",
        data={"csrf_token": "test-csrf-value", "is_active": "false"},
    )

    assert users_page.status_code == 200
    assert logins_page.status_code == 200
    assert "session-member" not in logins_page.text
    assert "csrf_token_hash" not in logins_page.text
    assert created.status_code == 200
    assert "temporary-password-shown-once" in created.text
    assert deactivated.status_code == 303
    assert users.rows[1].is_active is False


def test_admin_can_edit_roles_and_revoke_one_active_login_with_csrf() -> None:
    """A missing role control, CSRF gate, or targeted-login revocation must change this result."""
    client, _, users = _client()
    _login(client, "admin@example.test")

    users_page = client.get("/admin/users")
    changed_roles = client.post(
        f"/admin/users/{users.member_id}/roles",
        data={"csrf_token": "test-csrf-value", "roles": "admin,user"},
    )
    logins_page = client.get("/admin/logins")
    csrf_failure = client.post(f"/admin/logins/{users.login_id}/revoke")
    revoked = client.post(
        f"/admin/logins/{users.login_id}/revoke",
        data={"csrf_token": "test-csrf-value"},
    )
    after_revoke = client.get("/admin/logins")

    assert f'action="/admin/users/{users.member_id}/roles"' in users_page.text
    assert 'name="roles"' in users_page.text
    assert changed_roles.status_code == 303
    assert users.rows[1].roles == ["admin", "user"]
    assert ("roles_changed", users.member_id, {"roles": "admin,user"}) in users.audit_events
    assert f'action="/admin/logins/{users.login_id}/revoke"' in logins_page.text
    assert csrf_failure.status_code == 403
    assert revoked.status_code == 303
    assert users.login_rows[0].revoked_at is not None
    assert (
        "login_revoked",
        users.member_id,
        {"session_id": str(users.login_id)},
    ) in users.audit_events
    assert "Revoked" in after_revoke.text
    assert f'action="/admin/logins/{users.login_id}/revoke"' not in after_revoke.text


def test_forced_password_change_only_allows_change_or_logout_then_requires_new_login() -> None:
    """Broad forced-password access or retaining the old browser session must fail."""
    client, _, _ = _client()
    _login(client, "forced@example.test")

    blocked = client.get("/settings")
    changed = client.post(
        "/password/change",
        data={
            "csrf_token": "test-csrf-value",
            "current_password": "correct horse battery staple",
            "new_password": "a distinct replacement password",
        },
    )
    after_change = client.get("/settings")

    assert blocked.status_code == 303
    assert blocked.headers["location"] == "/password/change"
    assert changed.status_code == 303
    assert changed.headers["location"] == "/login"
    assert after_change.status_code == 303
    assert after_change.headers["location"] == "/login"
