"""Navigation rules for the authenticated application shell."""

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from project_recovery.admin.shell import AppServices, navigation_items
from project_recovery.app import create_app
from project_recovery.auth.sessions import CurrentUser
from project_recovery.config import Settings


def test_navigation_limits_standard_users_to_chat_and_settings() -> None:
    """Accidentally exposing an admin route to a standard user must change this result."""
    user = CurrentUser(
        user_id=None,  # type: ignore[arg-type]
        email="member@example.test",
        roles=("user",),
        force_password_change=False,
    )

    items = navigation_items(user, "/settings")

    assert [(item.label, item.href, item.active, item.group) for item in items] == [
        ("Chat", "/chat", False, "workspace"),
        ("Settings", "/settings", True, "workspace"),
    ]


def test_navigation_marks_only_the_matching_admin_route_active() -> None:
    """A broken role filter or active-route matcher must fail this public navigation contract."""
    admin = CurrentUser(
        user_id=None,  # type: ignore[arg-type]
        email="admin@example.test",
        roles=("admin",),
        force_password_change=False,
    )

    items = navigation_items(admin, "/admin/logins")

    assert [item.label for item in items] == [
        "Chat",
        "Settings",
        "Users",
        "Logins",
        "Prompt Runs",
        "Chat Feedback",
        "Model Usage",
        "Exceptions",
        "Knowledge",
        "Tool Use",
    ]
    assert [item.label for item in items if item.active] == ["Logins"]
    assert [item.group for item in items] == ["workspace", "workspace"] + ["admin"] * 8


class _NavigationAuth:
    async def current_user(self, token: str) -> CurrentUser | None:
        if token != "active-session":
            return None
        return CurrentUser(uuid4(), "admin@example.test", ("admin",), False)


class _NavigationDatabase:
    async def close(self) -> None:
        return None


def test_navigation_api_includes_group_and_current_state() -> None:
    """Dropping item group or active state from the public navigation payload must fail."""
    app = create_app(
        Settings(
            openai_api_key="test-key",
            openai_vector_store_id="vs_test",
            database_url="postgresql+asyncpg://test:test@localhost/test",
            app_session_secret="session-secret",
            chainlit_auth_secret="chainlit-secret",
        ),
        AppServices(
            database=_NavigationDatabase(),
            auth=_NavigationAuth(),  # type: ignore[arg-type]
            users=SimpleNamespace(),
        ),
    )
    client = TestClient(app)
    client.cookies.set("project_recovery_session", "active-session")

    response = client.get("/api/navigation")

    assert response.status_code == 200
    assert response.json()["items"][0] == {
        "label": "Chat",
        "href": "/chat",
        "active": False,
        "group": "workspace",
    }
    assert response.json()["items"][2]["group"] == "admin"
