"""Framework-neutral authentication route contracts for later application wiring."""

from dataclasses import dataclass

from project_recovery.auth.dependencies import require_csrf
from project_recovery.auth.sessions import AuthService, LoginResult


@dataclass(frozen=True, slots=True)
class CookieOptions:
    """Cookie flags which route adapters apply to their HTTP responses."""

    secure: bool
    http_only: bool
    same_site: str = "lax"
    path: str = "/"


@dataclass(frozen=True, slots=True)
class CookiePolicy:
    """Shared session and CSRF cookie policy for every future route adapter."""

    session: CookieOptions
    csrf: CookieOptions

    @classmethod
    def for_environment(cls, environment: str) -> "CookiePolicy":
        """Build safe production defaults while permitting local HTTP development."""
        secure = environment.strip().casefold() == "production"
        return cls(
            session=CookieOptions(secure=secure, http_only=True),
            csrf=CookieOptions(secure=secure, http_only=False),
        )


class AuthRoutes:
    """Small route facade keeping cookies and CSRF checks consistent across UI layers."""

    def __init__(self, auth: AuthService, policy: CookiePolicy) -> None:
        self.auth = auth
        self.policy = policy

    async def login(self, email: str, password: str) -> LoginResult | None:
        """Authenticate credentials; an adapter sets cookies only for a result."""
        return await self.auth.login(email, password)

    async def logout(self, session_token: str, csrf_token: str) -> bool:
        """Require CSRF before revoking a browser session."""
        await require_csrf(self.auth, session_token, csrf_token)
        return await self.auth.logout(session_token)

    async def change_password(
        self, session_token: str, csrf_token: str, current_password: str, new_password: str
    ) -> bool:
        """Require CSRF before a password change, which revokes every old session."""
        await require_csrf(self.auth, session_token, csrf_token)
        return await self.auth.change_password(session_token, current_password, new_password)
