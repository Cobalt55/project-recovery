"""User persistence queries."""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import Select, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.models import AppSetting, LoginSession, User, UserManagementEvent, utc_now
from project_recovery.repositories._safety import page_limit, page_offset, sanitize_metadata
from project_recovery.repositories._session import RepositoryBase


class UserRepository(RepositoryBase):
    """Persist users and provide bounded administrator-facing queries."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession] | AsyncSession) -> None:
        super().__init__(sessions)

    async def get_by_email(self, email: str) -> User | None:
        async with self._sessions() as session:
            statement = select(User).where(User.email == email.strip().casefold())
            return cast(User | None, await session.scalar(statement))

    async def get(self, user_id: object) -> User | None:
        async with self._sessions() as session:
            return cast(User | None, await session.get(User, user_id))

    async def create(
        self,
        email: str,
        display_name: str,
        password_hash: str,
        roles: list[str],
        force_password_change: bool,
    ) -> User:
        user = User(
            email=email.strip().casefold(),
            display_name=display_name[:200],
            password_hash=password_hash[:255],
            roles=[role[:32] for role in roles],
            force_password_change=force_password_change,
        )
        async with self._sessions() as session:
            session.add(user)
            await self._commit(session)
            await session.refresh(user)
        return user

    async def list_page(
        self, query: str | None, status: str | None, offset: int, limit: int
    ) -> Sequence[User]:
        statement: Select[tuple[User]] = select(User)
        if query:
            search = f"%{query.strip()}%"
            statement = statement.where(User.email.ilike(search) | User.display_name.ilike(search))
        if status == "active":
            statement = statement.where(User.is_active.is_(True))
        elif status == "inactive":
            statement = statement.where(User.is_active.is_(False))
        statement = (
            statement.order_by(User.created_at.desc())
            .offset(page_offset(offset))
            .limit(page_limit(limit))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def set_active(self, user_id: object, is_active: bool) -> User | None:
        async with self._sessions() as session:
            managed = await session.get(User, user_id)
            if managed is None:
                return None
            if (
                not is_active
                and "admin" in managed.roles
                and not await self._has_other_active_admin(session, managed.id)
            ):
                raise ValueError("at least one active administrator is required")
            managed.is_active = is_active
            if not is_active:
                await session.execute(
                    update(LoginSession)
                    .where(LoginSession.user_id == managed.id, LoginSession.revoked_at.is_(None))
                    .values(revoked_at=managed.updated_at)
                )
            await self._commit(session)
            await session.refresh(managed)
            return managed

    async def set_roles(self, user_id: object, roles: list[str]) -> User | None:
        """Replace roles with a bounded, already validated role list."""
        async with self._sessions() as session:
            managed = await session.get(User, user_id)
            if managed is None:
                return None
            if (
                "admin" in managed.roles
                and "admin" not in roles
                and managed.is_active
                and not await self._has_other_active_admin(session, managed.id)
            ):
                raise ValueError("at least one active administrator is required")
            managed.roles = [role[:32] for role in roles]
            await self._commit(session)
            await session.refresh(managed)
            return managed

    async def set_temporary_password(self, user_id: object, password_hash: str) -> User | None:
        """Store only an Argon2 hash and revoke each pre-reset browser session."""
        async with self._sessions() as session:
            managed = await session.get(User, user_id)
            if managed is None:
                return None
            managed.password_hash = password_hash[:255]
            managed.force_password_change = True
            await session.execute(
                update(LoginSession)
                .where(LoginSession.user_id == managed.id, LoginSession.revoked_at.is_(None))
                .values(revoked_at=managed.updated_at)
            )
            await self._commit(session)
            await session.refresh(managed)
            return managed

    async def get_settings(self, user_id: object) -> dict[str, str]:
        """Return the safe personal preference keys, or empty defaults."""
        async with self._sessions() as session:
            stored = await session.scalar(select(AppSetting).where(AppSetting.user_id == user_id))
            if stored is None:
                return {}
            return {
                key: value
                for key, value in stored.settings.items()
                if key in {"model", "reasoning_effort", "theme"} and isinstance(value, str)
            }

    async def save_settings(self, user_id: object, settings: dict[str, str]) -> dict[str, str]:
        """Upsert the approved personal preferences without accepting arbitrary JSON."""
        safe_settings = {
            key: value
            for key, value in settings.items()
            if key in {"model", "reasoning_effort", "theme"} and isinstance(value, str)
        }
        statement = (
            insert(AppSetting)
            .values(user_id=user_id, settings=safe_settings)
            .on_conflict_do_update(
                index_elements=[AppSetting.user_id], set_={"settings": safe_settings}
            )
            .returning(AppSetting.settings)
        )
        async with self._sessions() as session:
            result = await session.scalar(statement)
            await self._commit(session)
            return dict(result or {})

    async def list_logins(
        self, offset: int, limit: int, query: str | None = None, status: str | None = None
    ) -> Sequence[object]:
        """List bounded, secret-free session columns for the login history page."""
        if limit < 1:
            raise ValueError("limit must be positive")
        statement = select(
            LoginSession.id,
            LoginSession.user_id,
            User.email,
            User.is_active,
            LoginSession.created_at,
            LoginSession.last_seen_at,
            LoginSession.expires_at,
            LoginSession.revoked_at,
        ).join(User, LoginSession.user_id == User.id)
        normalized_query = (query or "").strip().casefold()[:320]
        if normalized_query:
            statement = statement.where(User.email.ilike(f"%{normalized_query}%"))
        if status == "active":
            statement = statement.where(
                User.is_active.is_(True),
                LoginSession.revoked_at.is_(None),
                LoginSession.expires_at > utc_now(),
            )
        elif status == "revoked":
            statement = statement.where(LoginSession.revoked_at.is_not(None))
        elif status == "expired":
            statement = statement.where(
                LoginSession.revoked_at.is_(None), LoginSession.expires_at <= utc_now()
            )
        statement = (
            statement.order_by(LoginSession.created_at.desc())
            .offset(page_offset(offset))
            .limit(min(limit, 101))
        )
        async with self._sessions() as session:
            return (await session.execute(statement)).all()

    async def revoke_login(self, login_id: object) -> object | None:
        """Revoke one session idempotently and return its user only if it was active."""
        async with self._sessions() as session:
            login = await session.get(LoginSession, login_id, with_for_update=True)
            if login is None or login.revoked_at is not None:
                return None
            login.revoked_at = utc_now()
            await self._commit(session)
            return login.user_id

    @staticmethod
    async def _has_other_active_admin(session: AsyncSession, user_id: object) -> bool:
        statement = select(User.id).where(
            User.id != user_id,
            User.is_active.is_(True),
            cast(Any, User.roles).any("admin"),
        )
        return (await session.scalar(statement)) is not None

    async def record_management_event(
        self,
        actor_user_id: object | None,
        target_user_id: object | None,
        action: str,
        metadata: dict[str, object],
    ) -> UserManagementEvent:
        event = UserManagementEvent(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action[:64],
            metadata_json=sanitize_metadata(metadata),
        )
        async with self._sessions() as session:
            session.add(event)
            await self._commit(session)
            await session.refresh(event)
        return event
