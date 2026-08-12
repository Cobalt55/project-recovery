"""Bounded Chat Feedback page view models."""

from collections.abc import Iterable
from typing import Any

from project_recovery.admin.formatting import safe_json, safe_text, timestamp


def feedback_rows(records: Iterable[Any]) -> list[dict[str, object]]:
    """Decorate feedback with sanitized, truncated context snapshots."""
    return [
        {
            "id": str(record.id),
            "user_id": str(record.user_id or ""),
            "conversation_id": str(record.conversation_id),
            "message_id": str(record.message_id or ""),
            "rating": record.rating,
            "comment": safe_text(record.comment, 2_000),
            "context": safe_json(record.context_snapshot),
            "model": safe_text(record.model, 128),
            "trace_id": safe_text(record.trace_id, 255),
            "tool_summary": safe_text(record.tool_summary, 2_000),
            "created_at": timestamp(record.created_at),
        }
        for record in records
    ]


__all__ = ["feedback_rows"]
