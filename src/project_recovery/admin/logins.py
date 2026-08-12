"""Login list presentation helpers."""

from datetime import datetime


def login_status(is_active: bool, revoked_at: datetime | None) -> str:
    """Return a concise, non-sensitive session state for the administrator table."""
    if revoked_at is not None:
        return "Revoked"
    return "Active" if is_active else "Inactive user"
