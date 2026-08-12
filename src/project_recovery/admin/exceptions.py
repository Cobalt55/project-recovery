"""Bounded Exceptions page view models."""

from collections.abc import Iterable
from typing import Any

from project_recovery.admin.formatting import safe_json, safe_text, timestamp


def exception_rows(records: Iterable[Any]) -> list[dict[str, object]]:
    """Decorate exception records with a second redaction boundary."""
    return [
        {
            "id": str(record.id),
            "type": safe_text(record.exception_type, 255),
            "path": safe_text(record.request_path, 2_048),
            "message": safe_text(record.message, 4_000),
            "occurrences": record.occurrence_count,
            "fingerprint": safe_text(record.fingerprint, 64),
            "stack": safe_text(record.stack_trace, 8_000),
            "context": safe_json(record.context),
            "first_seen_at": timestamp(record.first_seen_at),
            "last_seen_at": timestamp(record.last_seen_at),
        }
        for record in records
    ]


__all__ = ["exception_rows"]
