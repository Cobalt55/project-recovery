"""Recoverable OpenAI vector-store lifecycle for shared Knowledge."""

from __future__ import annotations

import asyncio
import io
import re
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from openai import NotFoundError

from project_recovery.repositories._safety import redact_text

MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}
FINAL_STATUSES = {"completed", "failed", "cancelled"}
SAFE_NAME = re.compile(r"^[^/\\\x00-\x1f\x7f]+$")


class KnowledgeValidationError(ValueError):
    """An uploaded file is not safe or supported."""


class KnowledgeService:
    """Persist first, then own every provider and local-file transition."""

    def __init__(
        self,
        *,
        repository: Any,
        openai_client: Any,
        vector_store_id: str,
        staging_root: str | Path,
        poll_interval: float = 1.0,
        poll_timeout: float = 120.0,
    ) -> None:
        self._repository = repository
        self._client = openai_client
        self._vector_store_id = vector_store_id
        self._staging_root = Path(staging_root).resolve()
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout

    async def queue_upload(
        self,
        *,
        filename: str,
        content: bytes,
        category: str | None,
        description: str | None,
    ) -> Any:
        """Validate, durably stage, and persist one queued resource."""
        safe_name, mime = validate_upload(filename, content)
        resource = await self._repository.create_queued(
            name=safe_name,
            content_type=mime,
            byte_size=len(content),
            category=_attribute(category, 64),
            description=_attribute(description, 512),
            metadata={},
        )
        path = self._staging_root / resource.id.hex / safe_name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return await self._repository.force_update(
                resource.id, metadata={"staging_path": str(path)}
            )
        except Exception:
            shutil.rmtree(path.parent, ignore_errors=True)
            await self._repository.force_update(
                resource.id, status="error", error_message="Unable to stage upload."
            )
            raise

    async def list_page(
        self,
        *,
        query: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> Any:
        """Expose the repository's bounded page without leaking it to routes."""
        return await self._repository.list_page(
            query=query, status=status, offset=offset, limit=limit
        )

    async def ingest(self, resource_id: UUID) -> None:
        """Ingest one queued resource, cleaning owned provider state on failure."""
        resource = await self._repository.get(resource_id)
        if resource is None or resource.status != "queued":
            return
        if not await self._repository.transition(resource.id, "queued", "processing"):
            return
        path = self._owned_staging_path(resource.metadata_json)
        provider_file_id: str | None = None
        try:
            if path is None or not path.is_file():
                raise RuntimeError("Staged file is unavailable.")
            uploaded = await self._client.files.create(
                file=(resource.name, path.read_bytes(), resource.content_type),
                purpose="assistants",
            )
            provider_file_id = uploaded.id
            await self._repository.force_update(
                resource.id,
                provider_file_id=provider_file_id,
                vector_store_file_id=provider_file_id,
            )
            attachment = await self._client.vector_stores.files.create(
                self._vector_store_id,
                file_id=provider_file_id,
                attributes={
                    "category": _attribute(resource.category, 64) or "General",
                    "description": _attribute(resource.description, 512) or "",
                },
            )
            attachment = await self._poll(provider_file_id, attachment)
            if attachment.status != "completed":
                detail = getattr(getattr(attachment, "last_error", None), "message", None)
                raise RuntimeError(str(detail or f"Ingestion {attachment.status}."))
            await self._repository.force_update(
                resource.id,
                status="ready",
                error_message=None,
                provider_file_id=provider_file_id,
                vector_store_file_id=provider_file_id,
                metadata={},
            )
            shutil.rmtree(path.parent, ignore_errors=True)
        except Exception as error:
            cleanup_error = await self._cleanup_provider(provider_file_id)
            message = redact_text(str(error), 1500) or "Knowledge ingestion failed."
            if cleanup_error:
                message = f"{message} Cleanup: {cleanup_error}"[:2000]
            await self._repository.force_update(
                resource.id,
                status="error",
                provider_file_id=None if not cleanup_error else provider_file_id,
                vector_store_file_id=None if not cleanup_error else provider_file_id,
                error_message=message,
            )

    async def retry(self, resource_id: UUID) -> bool:
        """Requeue only a fully cleaned error resource."""
        resource = await self._repository.get(resource_id)
        if (
            resource is None
            or resource.status != "error"
            or resource.provider_file_id
            or resource.vector_store_file_id
        ):
            return False
        return bool(
            await self._repository.transition(resource.id, "error", "queued", error_message=None)
        )

    async def delete(self, resource_id: UUID) -> bool:
        """Delete vector-store attachment, provider file, and staged bytes."""
        resource = await self._repository.get(resource_id)
        if resource is None or resource.status == "deleted":
            return resource is not None
        if resource.status != "deleting":
            if not await self._repository.transition(resource.id, resource.status, "deleting"):
                return False
            resource = await self._repository.get(resource_id)
        cleanup_error = await self._cleanup_provider(resource.provider_file_id)
        if cleanup_error:
            await self._repository.force_update(
                resource.id, status="deleting", error_message=cleanup_error
            )
            return False
        path = self._owned_staging_path(resource.metadata_json)
        if path is not None:
            shutil.rmtree(path.parent, ignore_errors=True)
        await self._repository.force_update(
            resource.id,
            status="deleted",
            provider_file_id=None,
            vector_store_file_id=None,
            error_message=None,
            metadata={},
        )
        return True

    async def recover_stale(self) -> int:
        """Requeue safe interrupted work or resume known provider attachments."""
        before = datetime.now(UTC) - timedelta(minutes=5)
        resources = await self._repository.list_stale_processing(before, 100)
        recovered = 0
        for resource in resources:
            if not resource.provider_file_id:
                await self._repository.force_update(resource.id, status="queued")
                recovered += 1
                continue
            try:
                attachment = await self._client.vector_stores.files.retrieve(
                    resource.provider_file_id,
                    vector_store_id=self._vector_store_id,
                )
            except NotFoundError:
                cleanup_error = await self._cleanup_provider(resource.provider_file_id)
                if cleanup_error:
                    await self._repository.force_update(
                        resource.id,
                        status="error",
                        error_message=f"Recovery cleanup: {cleanup_error}",
                    )
                    recovered += 1
                    continue
                await self._repository.force_update(
                    resource.id,
                    status="queued",
                    provider_file_id=None,
                    vector_store_file_id=None,
                )
                recovered += 1
                continue
            attachment = await self._poll(resource.provider_file_id, attachment)
            if attachment.status == "completed":
                path = self._owned_staging_path(resource.metadata_json)
                await self._repository.force_update(resource.id, status="ready", metadata={})
                if path is not None:
                    shutil.rmtree(path.parent, ignore_errors=True)
            else:
                await self._repository.force_update(
                    resource.id, status="error", error_message=f"Ingestion {attachment.status}."
                )
            recovered += 1
        return recovered

    async def _poll(self, file_id: str, initial: Any) -> Any:
        attachment = initial
        deadline = asyncio.get_running_loop().time() + self._poll_timeout
        while attachment.status not in FINAL_STATUSES:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Knowledge ingestion timed out.")
            await asyncio.sleep(self._poll_interval)
            attachment = await self._client.vector_stores.files.retrieve(
                file_id, vector_store_id=self._vector_store_id
            )
        return attachment

    async def _cleanup_provider(self, file_id: str | None) -> str | None:
        if not file_id:
            return None
        errors: list[str] = []
        try:
            await self._client.vector_stores.files.delete(
                file_id, vector_store_id=self._vector_store_id
            )
        except Exception as error:
            if not _not_found(error):
                errors.append(f"detach {type(error).__name__}")
        try:
            await self._client.files.delete(file_id)
        except Exception as error:
            if not _not_found(error):
                errors.append(f"file delete {type(error).__name__}")
        return ", ".join(errors) or None

    def _owned_staging_path(self, metadata: object) -> Path | None:
        path = _staging_path(metadata)
        if path is None:
            return None
        resolved = path.resolve()
        return resolved if resolved.is_relative_to(self._staging_root) else None


def validate_upload(filename: str, content: bytes) -> tuple[str, str]:
    """Validate file name, exact size boundary, and content structure."""
    name = filename.strip()
    if (
        not name
        or len(name) > 255
        or not SAFE_NAME.fullmatch(name)
        or name in {".", ".."}
        or ".." in Path(name).stem
    ):
        raise KnowledgeValidationError("Invalid filename.")
    extension = Path(name).suffix.casefold()
    mime = ALLOWED_TYPES.get(extension)
    if mime is None:
        raise KnowledgeValidationError("Unsupported file type.")
    if not content or len(content) > MAX_FILE_BYTES:
        raise KnowledgeValidationError("File must be between 1 byte and 25 MiB.")
    if extension == ".pdf" and not content.startswith(b"%PDF-"):
        raise KnowledgeValidationError("Invalid PDF content.")
    if extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = archive.namelist()
                if any(info.flag_bits & 0x1 for info in archive.infolist()):
                    raise KnowledgeValidationError("Encrypted DOCX files are not supported.")
                if any(name.startswith(("/", "\\")) or ".." in Path(name).parts for name in names):
                    raise KnowledgeValidationError("Unsafe DOCX archive.")
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise KnowledgeValidationError("Invalid DOCX content.")
        except zipfile.BadZipFile as error:
            raise KnowledgeValidationError("Invalid DOCX content.") from error
    if extension in {".txt", ".md"}:
        if b"\x00" in content:
            raise KnowledgeValidationError("Text files cannot contain NUL bytes.")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise KnowledgeValidationError("Text files must be UTF-8.") from error
    return name, mime


def _attribute(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized[:limit] or None


def _staging_path(metadata: object) -> Path | None:
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("staging_path")
    return Path(value) if isinstance(value, str) else None


def _not_found(error: Exception) -> bool:
    return isinstance(error, NotFoundError) or getattr(error, "status_code", None) == 404


__all__ = [
    "ALLOWED_TYPES",
    "KnowledgeService",
    "KnowledgeValidationError",
    "MAX_FILE_BYTES",
    "validate_upload",
]
