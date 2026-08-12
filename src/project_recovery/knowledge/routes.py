"""Knowledge route view helpers."""

from collections.abc import Iterable
from typing import Any

from project_recovery.admin.formatting import safe_text, timestamp

KNOWLEDGE_STATUSES = ("queued", "processing", "ready", "error", "deleting", "deleted")


def knowledge_rows(records: Iterable[Any]) -> list[dict[str, object]]:
    """Decorate Knowledge records with bounded text."""
    return [
        {
            "id": str(record.id),
            "name": safe_text(record.name, 255),
            "content_type": safe_text(record.content_type, 127),
            "byte_size": record.byte_size,
            "category": safe_text(record.category, 128),
            "description": safe_text(record.description, 2_000),
            "status": safe_text(record.status, 32),
            "error": safe_text(record.error_message, 2_000),
            "updated_at": timestamp(record.updated_at),
        }
        for record in records
    ]


__all__ = ["KNOWLEDGE_STATUSES", "knowledge_rows"]
