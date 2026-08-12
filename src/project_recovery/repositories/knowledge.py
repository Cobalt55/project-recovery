"""Durable shared Knowledge ingestion persistence queries."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.models import KnowledgeResource, utc_now
from project_recovery.repositories._safety import bounded_text, sanitize_metadata
from project_recovery.repositories._session import RepositoryBase


class KnowledgeRepository(RepositoryBase):
    """Persist recoverable shared Knowledge resource ingestion state."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession] | AsyncSession) -> None:
        super().__init__(sessions)

    async def create_queued(
        self,
        *,
        name: str,
        content_type: str,
        byte_size: int,
        category: str | None,
        description: str | None,
        metadata: dict[str, object] | None,
    ) -> KnowledgeResource:
        resource = KnowledgeResource(
            name=name[:255],
            content_type=content_type[:127],
            byte_size=byte_size,
            category=bounded_text(category, 128),
            description=bounded_text(description, 2000),
            status="queued",
            metadata_json=sanitize_metadata(metadata),
        )
        async with self._sessions() as session:
            session.add(resource)
            await self._commit(session)
            await session.refresh(resource)
        return resource

    async def get(self, resource_id: UUID) -> KnowledgeResource | None:
        async with self._sessions() as session:
            return await session.get(KnowledgeResource, resource_id)

    async def list_page(
        self,
        *,
        query: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> Sequence[KnowledgeResource]:
        """Return one bounded newest-first Knowledge page."""
        statement = select(KnowledgeResource)
        if query:
            statement = statement.where(KnowledgeResource.name.ilike(f"%{query.strip()[:200]}%"))
        if status:
            statement = statement.where(KnowledgeResource.status == status[:32])
        statement = (
            statement.order_by(KnowledgeResource.updated_at.desc())
            .offset(max(0, offset))
            .limit(min(max(limit, 1), 100))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def list_stale_processing(
        self, before: datetime, limit: int = 100
    ) -> Sequence[KnowledgeResource]:
        """Return bounded interrupted work for startup recovery."""
        statement = (
            select(KnowledgeResource)
            .where(
                KnowledgeResource.status == "processing",
                KnowledgeResource.updated_at < before,
            )
            .order_by(KnowledgeResource.updated_at.asc())
            .limit(min(max(limit, 1), 100))
        )
        async with self._sessions() as session:
            return (await session.scalars(statement)).all()

    async def force_update(self, resource_id: UUID, **changes: object) -> KnowledgeResource | None:
        """Update provider IDs and status after bounded recovery/cleanup work."""
        allowed = {
            "status",
            "provider_file_id",
            "vector_store_file_id",
            "error_message",
            "metadata",
        }
        values: dict[str, object] = {"updated_at": utc_now()}
        for key, value in changes.items():
            if key not in allowed:
                raise ValueError(f"Unsupported knowledge field: {key}")
            if key == "metadata":
                values["metadata_json"] = sanitize_metadata(
                    value if isinstance(value, dict) else None
                )
            elif key == "error_message":
                values[key] = bounded_text(str(value) if value is not None else None, 2000)
            elif key in {"provider_file_id", "vector_store_file_id"}:
                values[key] = bounded_text(str(value) if value is not None else None, 255)
            else:
                values[key] = str(value)[:32]
        async with self._sessions() as session:
            resource = await session.get(KnowledgeResource, resource_id)
            if resource is None:
                return None
            for key, value in values.items():
                setattr(resource, key, value)
            await self._commit(session)
            await session.refresh(resource)
            return resource

    async def transition(
        self,
        resource_id: UUID,
        expected_status: str,
        new_status: str,
        **changes: object,
    ) -> bool:
        allowed = {"provider_file_id", "vector_store_file_id", "error_message", "metadata"}
        values: dict[str, object] = {
            "status": new_status[:32],
            "updated_at": utc_now(),
        }
        for key, value in changes.items():
            if key not in allowed:
                raise ValueError(f"Unsupported knowledge transition field: {key}")
            if key == "metadata":
                values["metadata_json"] = sanitize_metadata(
                    value if isinstance(value, dict) else None
                )
            elif key == "error_message":
                values[key] = bounded_text(str(value) if value is not None else None, 2000)
            else:
                values[key] = bounded_text(str(value) if value is not None else None, 255)
        statement = (
            update(KnowledgeResource)
            .where(KnowledgeResource.id == resource_id, KnowledgeResource.status == expected_status)
            .values(**values)
        )
        async with self._sessions() as session:
            result = await session.execute(statement)
            await self._commit(session)
            return bool(getattr(result, "rowcount", 0) == 1)
