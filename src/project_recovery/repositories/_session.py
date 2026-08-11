"""Repository session ownership and transaction-composition helpers."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _SharedSessionContext(AbstractAsyncContextManager[AsyncSession]):
    """Yield a caller-owned session without closing or committing it."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


class RepositoryBase:
    """Let repositories either own a short session or join a caller transaction."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession] | AsyncSession) -> None:
        self._owns_session = not isinstance(sessions, AsyncSession)
        self._sessions: Callable[[], AbstractAsyncContextManager[AsyncSession]]
        if self._owns_session:
            self._sessions = sessions
        else:
            self._sessions = lambda: _SharedSessionContext(sessions)

    async def _commit(self, session: AsyncSession) -> None:
        """Commit only repository-owned sessions; flush caller-owned transactions."""
        if self._owns_session:
            await session.commit()
        else:
            await session.flush()
