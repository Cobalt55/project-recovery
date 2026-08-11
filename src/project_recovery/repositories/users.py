"""User persistence queries."""

from collections.abc import Sequence

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.models import User, UserManagementEvent
from project_recovery.repositories._safety import page_limit, page_offset, sanitize_metadata
from project_recovery.repositories._session import RepositoryBase


class UserRepository(RepositoryBase):
    """Persist users and provide bounded administrator-facing queries."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession] | AsyncSession) -> None:
        super().__init__(sessions)

    async def get_by_email(self, email: str) -> User | None:
        async with self._sessions() as session:
            statement = select(User).where(User.email == email.strip().casefold())
            return await session.scalar(statement)

    async def get(self, user_id: object) -> User | None:
        async with self._sessions() as session:
            return await session.get(User, user_id)

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
        user = await self.get(user_id)
        if user is None:
            return None
        async with self._sessions() as session:
            managed = await session.get(User, user_id)
            if managed is None:
                return None
            managed.is_active = is_active
            await self._commit(session)
            await session.refresh(managed)
            return managed

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
