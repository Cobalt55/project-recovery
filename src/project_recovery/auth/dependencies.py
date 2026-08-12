"""Route-facing authentication and authorization dependencies."""

from project_recovery.auth.sessions import AuthService, CurrentUser


class AuthenticationError(PermissionError):
    """Raised when no valid session identifies an active user."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated user lacks required authority."""


async def require_user(
    auth: AuthService, session_token: str, *, allow_password_change: bool = False
) -> CurrentUser:
    """Resolve a principal while enforcing the mandatory password-change gate."""
    user = await auth.current_user(session_token)
    if user is None:
        raise AuthenticationError("authentication required")
    if user.force_password_change and not allow_password_change:
        raise AuthorizationError("password change required")
    return user


async def require_admin(auth: AuthService, session_token: str) -> CurrentUser:
    """Require a user with the administrator role."""
    user = await require_user(auth, session_token)
    if not user.is_admin:
        raise AuthorizationError("administrator role required")
    return user


async def require_csrf(auth: AuthService, session_token: str, csrf_token: str) -> bool:
    """Require a valid independent CSRF value for a state-changing operation."""
    if not await auth.validate_csrf(session_token, csrf_token):
        raise AuthorizationError("CSRF validation failed")
    return True
