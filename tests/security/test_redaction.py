"""Security regression tests for operational diagnostics and trace metadata."""

import json

from project_recovery.admin.formatting import safe_json, safe_text
from project_recovery.repositories._safety import REDACTED, sanitize_metadata


def test_secret_assignments_are_removed_from_exception_text() -> None:
    """Credential-looking assignments never reach an administrator-facing string."""
    value = (
        "request failed api_key=sk-live-example; authorization=Bearer abc123; "
        "cookie=session-cookie; password=temporary-password"
    )

    redacted = safe_text(value)

    assert "sk-live-example" not in redacted
    assert "Bearer abc123" not in redacted
    assert "session-cookie" not in redacted
    assert "temporary-password" not in redacted
    assert redacted.count(REDACTED) == 4


def test_secret_keys_are_replaced_before_json_serialization() -> None:
    """Sensitive metadata keys are replaced even when values are nested or non-text."""
    metadata = {
        "api_key": "sk-live-example",
        "nested": {
            "authorization": "Bearer abc123",
            "normal": "safe context",
            "items": [{"password": "temporary-password"}],
        },
    }

    sanitized = sanitize_metadata(metadata)
    rendered = safe_json(metadata)

    assert sanitized["api_key"] == REDACTED
    assert sanitized["nested"]["authorization"] == REDACTED
    assert sanitized["nested"]["items"][0]["password"] == REDACTED
    assert "sk-live-example" not in rendered
    assert "Bearer abc123" not in rendered
    assert "temporary-password" not in rendered
    assert json.loads(rendered)["api_key"] == REDACTED


def test_diagnostics_are_bounded_and_do_not_leak_database_urls() -> None:
    """Large failures and connection strings stay bounded and credential-free."""
    database_url = "postgresql+asyncpg://db-user:db-password@db.example.test:5432/app"
    rendered = safe_json({"error": database_url, "padding": "x" * 20_000})

    assert len(rendered.encode("utf-8")) <= 4_000
    assert database_url not in rendered
    assert "db-password" not in rendered
