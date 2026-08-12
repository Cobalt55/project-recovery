"""Database-backed, idle-expiring browser session management."""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from project_recovery.auth.passwords import PasswordService
from project_recovery.models import LoginSession, User, UserManagementEvent
from project_recovery.repositories._session import RepositoryBase

SESSION_IDLE_TIMEOUT = timedelta(hours=12)
LAST_SEEN_WRITE_INTERVAL = timedelta(minutes=5)


def token_hash(token: str) -> str:
    """Return the fixed-width SHA-256 representation stored for bearer material."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """Authenticated principal data that route layers may safely consume."""

    user_id: UUID
    email: str
    roles: tuple[str, ...]
    force_password_change: bool

    @property
    def is_admin(self) -> bool:
        """Whether the principal holds the administrator role."""
        return "admin" in self.roles


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Raw bearer values returned exactly once to the browser-facing layer."""

    session_id: UUID
    session_token: str
    csrf_token: str


class AuthService(RepositoryBase):
    """Compose password, session, and audit changes in one database boundary."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession] | AsyncSession,
        passwords: PasswordService,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        super().__init__(sessions)
        self._passwords = passwords
        self._now = now

    async def login(self, email: str, password: str) -> LoginResult | None:
        """Authenticate a user and issue independently random session and CSRF tokens."""
        normalized_email = email.strip().casefold()
        now = self._now()
        async with self._sessions() as session:
            user = await session.scalar(select(User).where(User.email == normalized_email))
            if user is None:
                self._passwords.verify_dummy(password)
                await self._audit(session, None, "login_failed")
                await self._commit(session)
                return None
            password_ok = self._passwords.verify(user.password_hash, password)
            if not password_ok or not user.is_active:
                await self._audit(session, user.id, "login_failed")
                await self._commit(session)
                return None
            if self._passwords.needs_rehash(user.password_hash):
                user.password_hash = self._passwords.hash(password)
            session_token = secrets.token_urlsafe(32)
            csrf_token = secrets.token_urlsafe(32)
            login_session = LoginSession(
                user_id=user.id,
                token_hash=token_hash(session_token),
                csrf_token_hash=token_hash(csrf_token),
                created_at=now,
                last_seen_at=now,
                expires_at=now + SESSION_IDLE_TIMEOUT,
            )
            session.add(login_session)
            user.last_login_at = now
            await self._audit(session, user.id, "login_succeeded")
            await self._commit(session)
            await session.refresh(login_session)
            return LoginResult(login_session.id, session_token, csrf_token)

    async def current_user(
        self, session_token: str, *, now: datetime | None = None
    ) -> CurrentUser | None:
        """Resolve a token only for a current, active user within the idle window."""
        current_time = now or self._now()
        async with self._sessions() as session:
            login_session = await session.scalar(
                select(LoginSession).where(LoginSession.token_hash == token_hash(session_token))
            )
            if login_session is None or login_session.revoked_at is not None:
                return None
            user = await session.get(User, login_session.user_id)
            if user is None or not user.is_active:
                return None
            if current_time - login_session.last_seen_at >= SESSION_IDLE_TIMEOUT:
                login_session.revoked_at = current_time
                await self._commit(session)
                return None
            if current_time - login_session.last_seen_at >= LAST_SEEN_WRITE_INTERVAL:
                login_session.last_seen_at = current_time
                login_session.expires_at = current_time + SESSION_IDLE_TIMEOUT
                await self._commit(session)
            return CurrentUser(user.id, user.email, tuple(user.roles), user.force_password_change)

    async def validate_csrf(self, session_token: str, csrf_token: str) -> bool:
        """Validate the distinct CSRF secret against a usable server-side session."""
        if await self.current_user(session_token) is None:
            return False
        async with self._sessions() as session:
            stored = await session.scalar(
                select(LoginSession).where(LoginSession.token_hash == token_hash(session_token))
            )
            return stored is not None and hmac.compare_digest(
                stored.csrf_token_hash, token_hash(csrf_token)
            )

    async def logout(self, session_token: str) -> bool:
        """Revoke this session without revealing whether it was valid."""
        async with self._sessions() as session:
            result = await session.execute(
                update(LoginSession)
                .where(
                    LoginSession.token_hash == token_hash(session_token),
                    LoginSession.revoked_at.is_(None),
                )
                .values(revoked_at=self._now())
            )
            await self._commit(session)
            return bool(result.rowcount)

    async def change_password(
        self, session_token: str, current_password: str, new_password: str
    ) -> bool:
        """Replace a verified password and revoke all sessions atomically."""
        now = self._now()
        async with self._sessions() as session:
            login_session = await session.scalar(
                select(LoginSession).where(LoginSession.token_hash == token_hash(session_token))
            )
            if login_session is None or login_session.revoked_at is not None:
                return False
            if now - login_session.last_seen_at >= SESSION_IDLE_TIMEOUT:
                login_session.revoked_at = now
                await self._commit(session)
                return False
            user = await session.get(User, login_session.user_id)
            if (
                user is None
                or not user.is_active
                or not self._passwords.verify(user.password_hash, current_password)
            ):
                return False
            user.password_hash = self._passwords.hash(new_password)
            user.force_password_change = False
            await session.execute(
                update(LoginSession)
                .where(
                    LoginSession.user_id == user.id,
                    LoginSession.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await self._audit(session, user.id, "password_changed")
            await self._commit(session)
            return True

    async def _audit(self, session: AsyncSession, target_user_id: UUID | None, action: str) -> None:
        session.add(
            UserManagementEvent(
                actor_user_id=target_user_id if action != "login_failed" else None,
                target_user_id=target_user_id,
                action=action,
                metadata_json={},
            )
        )
