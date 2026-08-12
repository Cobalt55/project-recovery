"""Database-backed, idle-expiring browser session management."""

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
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
    session_token: str = field(repr=False, compare=False)
    csrf_token: str = field(repr=False, compare=False)


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
                await self._passwords.verify_dummy_async(password)
                await self._audit(session, None, "login_failed")
                await self._commit(session)
                return None
            password_ok = await self._passwords.verify_async(user.password_hash, password)
            if not password_ok or not user.is_active:
                await self._audit(session, user.id, "login_failed")
                await self._commit(session)
                return None
            if await self._passwords.needs_rehash_async(user.password_hash):
                user.password_hash = await self._passwords.hash_async(password)
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
            lifecycle = await self._valid_lifecycle(session, session_token, current_time)
            if lifecycle is None:
                return None
            login_session, user = lifecycle
            if current_time - login_session.last_seen_at >= LAST_SEEN_WRITE_INTERVAL:
                login_session.last_seen_at = current_time
                login_session.expires_at = current_time + SESSION_IDLE_TIMEOUT
                await self._commit(session)
            return CurrentUser(user.id, user.email, tuple(user.roles), user.force_password_change)

    async def validate_csrf(self, session_token: str, csrf_token: str) -> bool:
        """Validate the distinct CSRF secret against a usable server-side session."""
        current_time = self._now()
        async with self._sessions() as session:
            lifecycle = await self._valid_lifecycle(
                session, session_token, current_time, csrf_token=csrf_token, lock=True
            )
            if lifecycle is None:
                return False
            login_session, _ = lifecycle
            if current_time - login_session.last_seen_at >= LAST_SEEN_WRITE_INTERVAL:
                login_session.last_seen_at = current_time
                login_session.expires_at = current_time + SESSION_IDLE_TIMEOUT
                await self._commit(session)
            return True

    async def logout(self, session_token: str) -> None:
        """Best-effort revoke a session without revealing whether it was valid."""
        async with self._sessions() as session:
            await session.execute(
                update(LoginSession)
                .where(
                    LoginSession.token_hash == token_hash(session_token),
                    LoginSession.revoked_at.is_(None),
                )
                .values(revoked_at=self._now())
            )
            await self._commit(session)
        return None

    async def rotate_session(self, session_token: str, csrf_token: str) -> LoginResult | None:
        """Atomically exchange one authenticated browser session for fresh bearer values."""
        now = self._now()
        async with self._sessions() as session:
            lifecycle = await self._valid_lifecycle(
                session, session_token, now, csrf_token=csrf_token, lock=True
            )
            if lifecycle is None:
                return None
            old_session, user = lifecycle
            fresh_session_token = secrets.token_urlsafe(32)
            fresh_csrf_token = secrets.token_urlsafe(32)
            fresh = LoginSession(
                user_id=user.id,
                token_hash=token_hash(fresh_session_token),
                csrf_token_hash=token_hash(fresh_csrf_token),
                created_at=now,
                last_seen_at=now,
                expires_at=now + SESSION_IDLE_TIMEOUT,
            )
            old_session.revoked_at = now
            session.add(fresh)
            await self._commit(session)
            await session.refresh(fresh)
            return LoginResult(fresh.id, fresh_session_token, fresh_csrf_token)

    async def change_password(
        self, session_token: str, current_password: str, new_password: str
    ) -> bool:
        """Replace a verified password and revoke all sessions atomically."""
        now = self._now()
        async with self._sessions() as session:
            lifecycle = await self._valid_lifecycle(session, session_token, now, lock=True)
            if lifecycle is None:
                return False
            login_session, user = lifecycle
            if not await self._passwords.verify_async(user.password_hash, current_password):
                return False
            if not self._passwords.is_acceptable_replacement(current_password, new_password):
                return False
            user.password_hash = await self._passwords.hash_async(new_password)
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

    async def _valid_lifecycle(
        self,
        session: AsyncSession,
        session_token: str,
        current_time: datetime,
        *,
        csrf_token: str | None = None,
        lock: bool = False,
    ) -> tuple[LoginSession, User] | None:
        """Read and, when needed, revoke one lifecycle-valid session in a single query."""
        statement = (
            select(LoginSession, User)
            .join(User, LoginSession.user_id == User.id)
            .where(
                LoginSession.token_hash == token_hash(session_token),
                LoginSession.revoked_at.is_(None),
                User.is_active.is_(True),
            )
        )
        if csrf_token is not None:
            statement = statement.where(LoginSession.csrf_token_hash == token_hash(csrf_token))
        if lock:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        login_session, user = row
        if (
            current_time - login_session.last_seen_at >= SESSION_IDLE_TIMEOUT
            or current_time >= login_session.expires_at
        ):
            login_session.revoked_at = current_time
            await self._commit(session)
            return None
        return login_session, user

    async def _audit(self, session: AsyncSession, target_user_id: UUID | None, action: str) -> None:
        session.add(
            UserManagementEvent(
                actor_user_id=target_user_id if action != "login_failed" else None,
                target_user_id=target_user_id,
                action=action,
                metadata_json={},
            )
        )
