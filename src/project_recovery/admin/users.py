"""Bounded administrator user-management service."""

import secrets
from collections.abc import Sequence
from uuid import UUID

from project_recovery.auth.passwords import MIN_REPLACEMENT_PASSWORD_LENGTH, PasswordService
from project_recovery.db import Database
from project_recovery.models import User
from project_recovery.repositories.users import UserRepository

TEMPORARY_PASSWORD_BYTES = 24
VALID_ROLES = {"admin", "user"}


class UserManagementService:
    """Compose user writes, session revocation, and audit records per request."""

    def __init__(self, database: Database, passwords: PasswordService) -> None:
        self._database = database
        self._passwords = passwords

    async def get_settings(self, user_id: UUID) -> dict[str, str]:
        return await UserRepository(self._database.session()).get_settings(user_id)

    async def save_settings(self, user_id: UUID, settings: dict[str, str]) -> dict[str, str]:
        return await UserRepository(self._database.session()).save_settings(user_id, settings)

    async def list_page(
        self, query: str | None, status: str | None, offset: int, limit: int
    ) -> Sequence[User]:
        return await UserRepository(self._database.session()).list_page(
            query, status, offset, limit
        )

    async def list_logins(self, offset: int, limit: int) -> object:
        return await UserRepository(self._database.session()).list_logins(offset, limit)

    async def create_user(
        self, actor_id: UUID, email: str, display_name: str, roles: list[str]
    ) -> str:
        temporary_password = self._temporary_password()
        normalized_roles = self._validated_roles(roles)
        password_hash = await self._passwords.hash_async(temporary_password)
        async with self._database.transaction() as session:
            users = UserRepository(session)
            user = await users.create(
                email=email,
                display_name=display_name,
                password_hash=password_hash,
                roles=normalized_roles,
                force_password_change=True,
            )
            await users.record_management_event(
                actor_id, user.id, "user_created", {"roles": normalized_roles}
            )
        return temporary_password

    async def reset_password(self, actor_id: UUID, user_id: UUID) -> str:
        temporary_password = self._temporary_password()
        password_hash = await self._passwords.hash_async(temporary_password)
        async with self._database.transaction() as session:
            users = UserRepository(session)
            user = await users.set_temporary_password(user_id, password_hash)
            if user is None:
                raise ValueError("user not found")
            await users.record_management_event(actor_id, user.id, "password_reset", {})
        return temporary_password

    async def set_active(self, actor_id: UUID, user_id: UUID, is_active: bool) -> None:
        async with self._database.transaction() as session:
            users = UserRepository(session)
            user = await users.set_active(user_id, is_active)
            if user is None:
                raise ValueError("user not found")
            await users.record_management_event(
                actor_id, user.id, "user_activated" if is_active else "user_deactivated", {}
            )

    async def set_roles(self, actor_id: UUID, user_id: UUID, roles: list[str]) -> None:
        normalized_roles = self._validated_roles(roles)
        async with self._database.transaction() as session:
            users = UserRepository(session)
            user = await users.set_roles(user_id, normalized_roles)
            if user is None:
                raise ValueError("user not found")
            await users.record_management_event(
                actor_id, user.id, "roles_changed", {"roles": normalized_roles}
            )

    async def revoke_login(self, actor_id: UUID, login_id: UUID) -> bool:
        """Revoke one browser session and audit it only when its state changes."""
        async with self._database.transaction() as session:
            users = UserRepository(session)
            user_id = await users.revoke_login(login_id)
            if user_id is None:
                return False
            await users.record_management_event(
                actor_id, user_id, "login_revoked", {"session_id": str(login_id)}
            )
        return True

    @staticmethod
    def _validated_roles(roles: list[str]) -> list[str]:
        normalized = sorted({role.strip().casefold() for role in roles if role.strip()})
        if not normalized or not set(normalized).issubset(VALID_ROLES):
            raise ValueError("invalid roles")
        return normalized

    @staticmethod
    def _temporary_password() -> str:
        # The bearer exists only in this response path; persistence receives its Argon2 hash.
        return secrets.token_urlsafe(TEMPORARY_PASSWORD_BYTES)[
            : MIN_REPLACEMENT_PASSWORD_LENGTH + 12
        ]
