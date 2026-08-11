"""Bound and sanitize untrusted persistence context before it reaches PostgreSQL."""

import re
from collections.abc import Mapping
from typing import Any

MAX_CONTEXT_STRING_LENGTH = 4_000
MAX_CONTEXT_ITEMS = 100
REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"(api[_-]?key|authorization|cookie|password|secret|token)", re.I)
_SENSITIVE_VALUE = re.compile(
    r"(?i)(api[_-]?key|authorization|cookie|password|secret|token)(\s*[:=]\s*)[^\s,;]+"
)


def bounded_text(value: str | None, limit: int) -> str | None:
    """Truncate text to its column's safe maximum without logging its content."""
    if value is None:
        return None
    return value[:limit]


def redact_text(value: str | None, limit: int) -> str | None:
    """Remove common credential assignments and apply a storage bound."""
    if value is None:
        return None
    return _SENSITIVE_VALUE.sub(r"\1\2" + REDACTED, value)[:limit]


def sanitize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return JSON-compatible, size-bounded metadata with secret-looking keys redacted."""
    if value is None:
        return {}

    def sanitize(item: Any, key: str | None = None) -> Any:
        if key and _SENSITIVE_KEY.search(key):
            return REDACTED
        if isinstance(item, Mapping):
            return {
                str(child_key)[:128]: sanitize(child_value, str(child_key))
                for child_key, child_value in list(item.items())[:MAX_CONTEXT_ITEMS]
            }
        if isinstance(item, list | tuple):
            return [sanitize(child) for child in item[:MAX_CONTEXT_ITEMS]]
        if isinstance(item, str):
            return redact_text(item, MAX_CONTEXT_STRING_LENGTH)
        if item is None or isinstance(item, bool | int | float):
            return item
        return bounded_text(str(item), MAX_CONTEXT_STRING_LENGTH)

    sanitized = sanitize(value)
    assert isinstance(sanitized, dict)
    return sanitized


def page_limit(limit: int) -> int:
    """Keep user-facing repository reads bounded to one hundred records."""
    if limit < 1:
        raise ValueError("limit must be positive")
    return min(limit, 100)


def page_offset(offset: int) -> int:
    """Reject negative pagination offsets rather than issuing broad queries."""
    if offset < 0:
        raise ValueError("offset must not be negative")
    return offset
