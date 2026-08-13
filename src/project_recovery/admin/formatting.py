"""Safe, bounded view formatting for operational administration pages."""

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from project_recovery.repositories._safety import redact_text, sanitize_metadata


def safe_text(value: object, limit: int = 2_000) -> str:
    """Redact common credential assignments before template auto-escaping."""
    return redact_text(str(value or ""), limit) or ""


def safe_json(value: object, limit: int = 4_000) -> str:
    """Render sanitized JSON without allowing a large context dump."""
    mapping = value if isinstance(value, Mapping) else {"value": value}
    sanitized = sanitize_metadata(mapping)
    return json.dumps(sanitized, ensure_ascii=True, sort_keys=True)[:limit]


def timestamp(value: Any) -> str:
    """Format aware timestamps consistently without assuming ORM types."""
    return value.isoformat() if isinstance(value, datetime) else ""


def format_timestamp(value: Any) -> dict[str, str]:
    """Provide a compact UTC label while retaining an exact machine-readable timestamp."""
    exact = timestamp(value)
    if not isinstance(value, datetime):
        return {"exact": "", "display": "Not recorded"}
    return {
        "exact": exact,
        "display": value.astimezone(UTC).strftime("%b %d, %Y %H:%M UTC"),
    }


__all__ = ["format_timestamp", "safe_json", "safe_text", "timestamp"]
