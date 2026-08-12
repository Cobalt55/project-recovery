"""Navigation rules for the authenticated application shell."""

from project_recovery.admin.shell import navigation_items
from project_recovery.auth.sessions import CurrentUser


def test_navigation_limits_standard_users_to_chat_and_settings() -> None:
    """Accidentally exposing an admin route to a standard user must change this result."""
    user = CurrentUser(
        user_id=None,  # type: ignore[arg-type]
        email="member@example.test",
        roles=("user",),
        force_password_change=False,
    )

    items = navigation_items(user, "/settings")

    assert [(item.label, item.href, item.active) for item in items] == [
        ("Chat", "/chat", False),
        ("Settings", "/settings", True),
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
        "Tool Use",
    ]
    assert [item.label for item in items if item.active] == ["Logins"]
