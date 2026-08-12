"""Shared application-shell contracts and role-filtered navigation."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from project_recovery.auth.sessions import AuthService, CurrentUser


@dataclass(frozen=True, slots=True)
class NavigationItem:
    """One visible, accessible shell navigation destination."""

    label: str
    href: str
    active: bool


_USER_ITEMS = (("Chat", "/chat"), ("Settings", "/settings"))
_ADMIN_ITEMS = (("Users", "/admin/users"), ("Logins", "/admin/logins"))


def navigation_items(user: CurrentUser, path: str) -> list[NavigationItem]:
    """Return only the approved destinations visible to a principal."""
    entries = _USER_ITEMS + (_ADMIN_ITEMS if user.is_admin else ())
    return [NavigationItem(label, href, path == href) for label, href in entries]


class DatabaseBoundary(Protocol):
    """Small health/lifecycle surface used by the web factory."""

    async def ping(self) -> bool: ...

    async def close(self) -> None: ...


class UserAdminBoundary(Protocol):
    """Route-facing administration operations without persistence coupling."""

    async def get_settings(self, user_id: UUID) -> dict[str, str]: ...

    async def save_settings(self, user_id: UUID, settings: dict[str, str]) -> dict[str, str]: ...

    async def list_page(
        self, query: str | None, status: str | None, offset: int, limit: int
    ) -> object: ...

    async def list_logins(self, offset: int, limit: int) -> object: ...

    async def create_user(
        self, actor_id: UUID, email: str, display_name: str, roles: list[str]
    ) -> str: ...

    async def reset_password(self, actor_id: UUID, user_id: UUID) -> str: ...

    async def set_active(self, actor_id: UUID, user_id: UUID, is_active: bool) -> None: ...

    async def set_roles(self, actor_id: UUID, user_id: UUID, roles: list[str]) -> None: ...

    async def revoke_login(self, actor_id: UUID, login_id: UUID) -> bool: ...


@dataclass(slots=True)
class AppServices:
    """Explicit application dependencies, also allowing deterministic route tests."""

    database: DatabaseBoundary
    auth: AuthService
    users: UserAdminBoundary
    chat: Any | None = None
