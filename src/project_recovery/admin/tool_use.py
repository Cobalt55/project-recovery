"""Bounded Tool Use page view models."""

from collections.abc import Iterable
from typing import Any

from project_recovery.admin.formatting import safe_json, safe_text, timestamp


def tool_run_rows(records: Iterable[Any]) -> list[dict[str, object]]:
    """Decorate tool runs without exposing raw arguments or output."""
    return [
        {
            "id": str(record.id),
            "trace_id": safe_text(record.trace_id, 255),
            "name": safe_text(record.tool_name, 128),
            "type": safe_text(record.tool_type, 64),
            "status": safe_text(record.status, 32),
            "duration_ms": record.duration_ms,
            "result_count": record.result_count,
            "summary": safe_text(record.result_summary, 2_000),
            "arguments": safe_json(record.arguments),
            "output": safe_json(record.output),
            "created_at": timestamp(record.created_at),
        }
        for record in records
    ]


__all__ = ["tool_run_rows"]
