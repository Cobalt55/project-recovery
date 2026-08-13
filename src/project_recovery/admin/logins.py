"""Login list presentation helpers."""

from datetime import datetime

from project_recovery.models import utc_now


def login_status(
    is_active: bool, revoked_at: datetime | None, expires_at: datetime
) -> str:
    """Return a concise, non-sensitive session state for the administrator table."""
    if revoked_at is not None:
        return "Revoked"
    if expires_at <= utc_now():
        return "Expired"
    return "Active" if is_active else "Inactive user"
