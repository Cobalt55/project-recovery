"""Bound and sanitize untrusted persistence context before it reaches PostgreSQL."""

import json
import math
import re
from collections.abc import Mapping
from typing import Any

MAX_CONTEXT_STRING_LENGTH = 4_000
MAX_CONTEXT_ITEMS = 100
MAX_CONTEXT_DEPTH = 8
MAX_CONTEXT_BYTES = 16_000
MAX_INTEGER_BITS = 4_096
REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(r"(api[_-]?key|authorization|cookie|password|secret|token)", re.I)
_SENSITIVE_VALUE = re.compile(
    r"(?im)(api[_-]?key|authorization|cookie|password|secret|token)(\s*[:=]\s*)[^\r\n,;]+"
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

    remaining = MAX_CONTEXT_BYTES

    def take_text(item: str) -> str:
        nonlocal remaining
        allowed = max(remaining, 0)
        result = redact_text(item, min(MAX_CONTEXT_STRING_LENGTH, allowed)) or ""
        remaining -= len(result.encode("utf-8"))
        return result

    def sanitize(item: Any, key: str | None = None, depth: int = 0) -> Any:
        if depth >= MAX_CONTEXT_DEPTH:
            return "[TRUNCATED]"
        if key and _SENSITIVE_KEY.search(key):
            return REDACTED
        if isinstance(item, Mapping):
            return {
                take_text(str(child_key)[:128]): sanitize(child_value, str(child_key), depth + 1)
                for child_key, child_value in list(item.items())[:MAX_CONTEXT_ITEMS]
                if remaining > 0
            }
        if isinstance(item, list | tuple):
            return [
                sanitize(child, depth=depth + 1)
                for child in item[:MAX_CONTEXT_ITEMS]
                if remaining > 0
            ]
        if isinstance(item, str):
            return take_text(item)
        if item is None or isinstance(item, bool):
            return item
        if isinstance(item, int):
            return item if item.bit_length() <= MAX_INTEGER_BITS else "[TRUNCATED]"
        if isinstance(item, float):
            return item if math.isfinite(item) else take_text(str(item))
        return take_text(str(item))

    sanitized = sanitize(value)
    assert isinstance(sanitized, dict)
    if len(json.dumps(sanitized, separators=(",", ":")).encode("utf-8")) > MAX_CONTEXT_BYTES:
        return {"_truncated": "[TRUNCATED]"}
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
