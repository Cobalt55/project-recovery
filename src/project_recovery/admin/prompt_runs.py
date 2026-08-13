"""Bounded Prompt Runs page view models."""

from collections.abc import Iterable
from typing import Any

from project_recovery.admin.formatting import format_timestamp, safe_text


def prompt_run_rows(records: Iterable[Any]) -> list[dict[str, object]]:
    """Decorate prompt-run records without exposing unsanitized prompts."""
    return [
        {
            "id": str(record.id),
            "user_id": str(record.user_id or ""),
            "conversation_id": str(record.conversation_id),
            "trace_id": safe_text(record.trace_id, 255),
            "model": safe_text(record.model, 128),
            "requested_effort": safe_text(record.requested_reasoning_effort, 16),
            "effective_effort": safe_text(record.effective_reasoning_effort, 16),
            "status": safe_text(record.status, 32),
            "prompt": safe_text(record.prompt, 1_000),
            "latency_ms": record.latency_ms,
            "total_tokens": record.total_tokens,
            "estimated_cost": record.estimated_cost,
            "started_at": format_timestamp(record.started_at),
        }
        for record in records
    ]


__all__ = ["prompt_run_rows"]
