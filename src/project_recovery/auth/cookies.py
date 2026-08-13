"""Cookie policy shared by the workspace and mounted Chainlit application."""

from chainlit.auth import create_jwt
from chainlit.user import User as ChainlitUser
from starlette.requests import Request
from starlette.responses import Response

from project_recovery.auth.sessions import CurrentUser
from project_recovery.config import Settings

SESSION_COOKIE = "project_recovery_session"
CSRF_COOKIE = "project_recovery_csrf"
CHAINLIT_COOKIE_PREFIX = "access_token"


def set_login_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
    current: CurrentUser,
    settings: Settings,
) -> None:
    """Set the application, CSRF, and Chainlit credentials after a successful login."""
    secure = settings.environment.casefold() == "production"
    response.set_cookie(
        SESSION_COOKIE, session_token, httponly=True, samesite="lax", secure=secure, path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, csrf_token, httponly=False, samesite="lax", secure=secure, path="/"
    )
    response.set_cookie(
        CHAINLIT_COOKIE_PREFIX,
        create_jwt(
            ChainlitUser(
                identifier=str(current.user_id),
                display_name=current.email,
                metadata={"roles": list(current.roles)},
            )
        ),
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
        max_age=12 * 60 * 60,
    )


def clear_login_cookies(response: Response, request: Request) -> None:
    """Clear application and mounted-Chainlit credentials together."""
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    for name in request.cookies:
        if name == CHAINLIT_COOKIE_PREFIX or name.startswith(f"{CHAINLIT_COOKIE_PREFIX}_"):
            response.delete_cookie(name, path="/")
