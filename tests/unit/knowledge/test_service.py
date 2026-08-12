"""Knowledge validation and provider lifecycle tests."""

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from project_recovery.knowledge.service import (
    MAX_FILE_BYTES,
    KnowledgeService,
    KnowledgeValidationError,
    validate_upload,
)


def _docx() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    return data.getvalue()


def test_upload_validation_enforces_type_size_name_and_content() -> None:
    assert validate_upload("guide.PDF", b"%PDF-safe")[1] == "application/pdf"
    assert validate_upload("guide.docx", _docx())[0] == "guide.docx"
    assert validate_upload("guide.md", b"# Safe")[1] == "text/markdown"
    validate_upload("exact.txt", b"x" * MAX_FILE_BYTES)
    for name, content in (
        ("../guide.txt", b"safe"),
        ("bad.exe", b"safe"),
        ("bad.pdf", b"not pdf"),
        ("bad.docx", b"not zip"),
        ("bad.txt", b"\x00"),
        ("large.txt", b"x" * (MAX_FILE_BYTES + 1)),
    ):
        with pytest.raises(KnowledgeValidationError):
            validate_upload(name, content)


class FakeRepository:
    def __init__(self) -> None:
        self.resource = None
        self.transitions: list[tuple[str, str]] = []

    async def create_queued(self, **values):
        self.resource = SimpleNamespace(
            id=uuid4(),
            status="queued",
            provider_file_id=None,
            vector_store_file_id=None,
            error_message=None,
            metadata_json=values["metadata"],
            **{key: value for key, value in values.items() if key != "metadata"},
        )
        return self.resource

    async def get(self, resource_id):
        return self.resource if self.resource and self.resource.id == resource_id else None

    async def force_update(self, resource_id, **values):
        assert self.resource.id == resource_id
        if "metadata" in values:
            self.resource.metadata_json = values.pop("metadata")
        for key, value in values.items():
            setattr(self.resource, key, value)
        return self.resource

    async def transition(self, resource_id, expected, new, **changes):
        assert self.resource.id == resource_id
        if self.resource.status != expected:
            return False
        self.transitions.append((expected, new))
        self.resource.status = new
        for key, value in changes.items():
            setattr(self.resource, key, value)
        return True

    async def list_stale_processing(self, before, limit):
        del before, limit
        return []


class FakeFiles:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def create(self, **kwargs):
        assert kwargs["purpose"] == "assistants"
        return SimpleNamespace(id="file-1")

    async def delete(self, file_id):
        self.deleted.append(file_id)


class FakeVectorFiles:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.attributes = None

    async def create(self, vector_store_id, **kwargs):
        assert vector_store_id == "vs-only"
        self.attributes = kwargs["attributes"]
        return SimpleNamespace(status="completed", last_error=None)

    async def retrieve(self, file_id, **kwargs):
        return SimpleNamespace(status="completed", last_error=None)

    async def delete(self, file_id, **kwargs):
        self.deleted.append(file_id)


@pytest.mark.asyncio
async def test_happy_ingestion_and_delete_own_provider_objects(tmp_path: Path) -> None:
    repository = FakeRepository()
    files = FakeFiles()
    vector_files = FakeVectorFiles()
    client = SimpleNamespace(
        files=files,
        vector_stores=SimpleNamespace(files=vector_files),
    )
    service = KnowledgeService(
        repository=repository,
        openai_client=client,
        vector_store_id="vs-only",
        staging_root=tmp_path,
        poll_interval=0,
    )

    resource = await service.queue_upload(
        filename="guide.txt",
        content=b"Safe guide",
        category="Guides",
        description="Shared guidance",
    )
    await service.ingest(resource.id)

    assert repository.resource.status == "ready"
    assert vector_files.attributes == {
        "category": "Guides",
        "description": "Shared guidance",
    }
    assert await service.delete(resource.id) is True
    assert vector_files.deleted == ["file-1"]
    assert files.deleted == ["file-1"]
    assert repository.resource.status == "deleted"


@pytest.mark.asyncio
async def test_provider_failure_cleans_up_and_leaves_retryable_error(tmp_path: Path) -> None:
    repository = FakeRepository()
    files = FakeFiles()

    class FailingVectorFiles(FakeVectorFiles):
        async def create(self, vector_store_id, **kwargs):
            raise RuntimeError("attach failed")

    vector_files = FailingVectorFiles()
    service = KnowledgeService(
        repository=repository,
        openai_client=SimpleNamespace(
            files=files,
            vector_stores=SimpleNamespace(files=vector_files),
        ),
        vector_store_id="vs-only",
        staging_root=tmp_path,
        poll_interval=0,
    )
    resource = await service.queue_upload(
        filename="guide.md", content=b"# Guide", category=None, description=None
    )

    await service.ingest(resource.id)

    assert repository.resource.status == "error"
    assert repository.resource.provider_file_id is None
    assert vector_files.deleted == ["file-1"]
    assert files.deleted == ["file-1"]
    assert await service.retry(resource.id) is True
    assert await service.retry(resource.id) is False
