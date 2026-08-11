"""Async PostgreSQL database lifecycle boundary."""

from collections.abc import Callable

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class Database:
    """Own the application PostgreSQL engine and its async sessions."""

    def __init__(self, url: str | SecretStr) -> None:
        database_url = url.get_secret_value() if isinstance(url, SecretStr) else url
        if not database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("Database requires a postgresql+asyncpg URL")
        self._engine = create_async_engine(database_url, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    def session(self) -> async_sessionmaker[AsyncSession]:
        """Return the session factory used by repository boundaries."""
        return self._sessions

    async def ping(self) -> bool:
        """Return whether PostgreSQL can accept a minimal query."""
        try:
            async with self._sessions() as session:
                await session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return False
        return True

    async def close(self) -> None:
        """Dispose the engine and all database connections."""
        await self._engine.dispose()


SessionFactory = Callable[[], AsyncSession]

__all__ = ["Database", "SessionFactory"]
