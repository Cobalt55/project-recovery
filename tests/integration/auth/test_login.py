"""PostgreSQL-backed authentication service coverage."""

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from project_recovery.auth.dependencies import (
    AuthorizationError,
    require_admin,
    require_csrf,
    require_user,
)
from project_recovery.auth.passwords import PasswordService
from project_recovery.auth.sessions import SESSION_IDLE_TIMEOUT, AuthService, token_hash
from project_recovery.db import Database
from project_recovery.models import LoginSession, UserManagementEvent
from project_recovery.repositories.users import UserRepository

POSTGRES_IMAGE = "postgres:16"
POSTGRES_PASSWORD = "test-password-only"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_alembic(database_url: str, revision: str) -> subprocess.CompletedProcess[str]:
    """Migrate the disposable database without exposing credentials in test output."""
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        env=os.environ | {"DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    """Run auth coverage against one disposable PostgreSQL 16 database."""
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for PostgreSQL integration tests")
    port = _free_port()
    name = f"project-recovery-auth-test-{uuid4().hex}"
    started = subprocess.run(
        [
            "docker",
            "run",
            "--detach",
            "--rm",
            "--name",
            name,
            "--publish",
            f"127.0.0.1:{port}:5432",
            "--env",
            "POSTGRES_DB=project_recovery_test",
            "--env",
            "POSTGRES_USER=project_recovery",
            "--env",
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            POSTGRES_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    container_id = started.stdout.strip()
    url = (
        "postgresql+asyncpg://project_recovery:"
        f"{POSTGRES_PASSWORD}@127.0.0.1:{port}/project_recovery_test"
    )

    async def wait_for_postgres() -> None:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                connection = await asyncpg.connect(
                    host="127.0.0.1",
                    port=port,
                    user="project_recovery",
                    password=POSTGRES_PASSWORD,
                    database="project_recovery_test",
                )
            except (OSError, asyncpg.PostgresError):
                await asyncio.sleep(0.5)
            else:
                await connection.close()
                return
        raise RuntimeError("disposable PostgreSQL container did not become ready")

    try:
        asyncio.run(wait_for_postgres())
        migrated = _run_alembic(url, "head")
        assert migrated.returncode == 0, migrated.stderr
        yield url
    finally:
        subprocess.run(["docker", "stop", container_id], check=False, capture_output=True)


def test_csrf_migration_upgrades_populated_legacy_sessions(postgres_url: str) -> None:
    """Upgrade legacy sessions with distinct, non-empty CSRF hashes before uniqueness."""
    downgraded = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260811_0001"],
        env=os.environ | {"DATABASE_URL": postgres_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert downgraded.returncode == 0, downgraded.stderr

    async def seed_legacy_sessions() -> None:
        connection = await asyncpg.connect(
            postgres_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        user_id = uuid4()
        now = datetime.now(UTC)
        try:
            await connection.execute(
                """
                INSERT INTO users (
                    id, email, display_name, password_hash, roles, is_active,
                    force_password_change, created_at, updated_at, last_login_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, NULL)
                """,
                user_id,
                "legacy@example.test",
                "Legacy User",
                "legacy-password-hash",
                ["user"],
                True,
                False,
                now,
            )
            for token in ("legacy-session-one", "legacy-session-two"):
                await connection.execute(
                    """
                    INSERT INTO login_sessions (
                        id, user_id, token_hash, created_at, last_seen_at, expires_at, revoked_at
                    ) VALUES ($1, $2, $3, $4, $4, $5, NULL)
                    """,
                    uuid4(),
                    user_id,
                    token_hash(token),
                    now,
                    now + SESSION_IDLE_TIMEOUT,
                )
        finally:
            await connection.close()

    asyncio.run(seed_legacy_sessions())
    upgraded = _run_alembic(postgres_url, "head")

    assert upgraded.returncode == 0, upgraded.stderr

    async def read_csrf_hashes() -> list[str]:
        connection = await asyncpg.connect(
            postgres_url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            return await connection.fetchval(
                "SELECT array_agg(csrf_token_hash ORDER BY token_hash) FROM login_sessions"
            )
        finally:
            await connection.close()

    csrf_hashes = asyncio.run(read_csrf_hashes())
    assert len(csrf_hashes) == 2
    assert len(set(csrf_hashes)) == 2
    assert all(len(value) == 64 for value in csrf_hashes)


@pytest_asyncio.fixture
async def database(postgres_url: str) -> AsyncIterator[Database]:
    database = Database(postgres_url)
    try:
        yield database
    finally:
        await database.close()


async def _create_user(database: Database, *, admin: bool = False, active: bool = True):
    service = PasswordService()
    user = await UserRepository(database.session()).create(
        email=f"{uuid4().hex}@example.test",
        display_name="Operator",
        password_hash=service.hash("correct horse battery staple"),
        roles=["admin"] if admin else ["user"],
        force_password_change=False,
    )
    if not active:
        await UserRepository(database.session()).set_active(user.id, False)
    return user


@pytest.mark.asyncio
async def test_login_stores_only_session_token_hash_and_audits_success(database: Database) -> None:
    """A successful login persists a hash and an audit event, not credential material."""
    user = await _create_user(database)
    auth = AuthService(database.session(), PasswordService())

    result = await auth.login(user.email, "correct horse battery staple")

    assert result is not None
    async with database.session()() as session:
        stored = await session.scalar(
            select(LoginSession).where(LoginSession.id == result.session_id)
        )
        event = await session.scalar(
            select(UserManagementEvent).order_by(UserManagementEvent.created_at)
        )
    assert stored is not None
    assert stored.token_hash == token_hash(result.session_token)
    assert stored.token_hash != result.session_token
    assert len(result.session_token) >= 43
    assert event is not None
    assert event.action == "login_succeeded"
    assert "password" not in event.metadata_json
    assert "token" not in event.metadata_json


@pytest.mark.asyncio
async def test_login_uses_generic_failure_for_unknown_or_inactive_user(database: Database) -> None:
    """Unknown and inactive accounts return the same non-enumerating result."""
    inactive = await _create_user(database, active=False)
    auth = AuthService(database.session(), PasswordService())

    assert await auth.login("missing@example.test", "wrong password") is None
    assert await auth.login(inactive.email, "correct horse battery staple") is None


@pytest.mark.asyncio
async def test_session_requires_active_user_and_12_hour_idle_window(database: Database) -> None:
    """Expired, revoked, and inactive sessions cannot identify a current user."""
    user = await _create_user(database)
    auth = AuthService(database.session(), PasswordService())
    login = await auth.login(user.email, "correct horse battery staple")
    assert login is not None

    current = await auth.current_user(login.session_token)
    assert current is not None
    assert current.user_id == user.id
    async with database.transaction() as session:
        stored = await session.get(LoginSession, login.session_id)
        assert stored is not None
        stored.last_seen_at = datetime.now(UTC) - SESSION_IDLE_TIMEOUT
        idle_boundary = stored.last_seen_at + SESSION_IDLE_TIMEOUT
    assert await auth.current_user(login.session_token, now=idle_boundary) is None

    fresh = await auth.login(user.email, "correct horse battery staple")
    assert fresh is not None
    await UserRepository(database.session()).set_active(user.id, False)
    assert await auth.current_user(fresh.session_token) is None


@pytest.mark.asyncio
async def test_password_change_revokes_old_session_and_forces_a_new_login(
    database: Database,
) -> None:
    """A password update invalidates every existing session for the user."""
    user = await _create_user(database)
    auth = AuthService(database.session(), PasswordService())
    login = await auth.login(user.email, "correct horse battery staple")
    assert login is not None

    assert await auth.change_password(
        login.session_token, "correct horse battery staple", "a new secure password"
    )
    assert await auth.current_user(login.session_token) is None
    assert await auth.login(user.email, "correct horse battery staple") is None
    assert await auth.login(user.email, "a new secure password") is not None


@pytest.mark.asyncio
async def test_password_change_rejects_reused_or_weak_replacement(database: Database) -> None:
    """A forced bootstrap password must be replaced by a distinct sufficiently long password."""
    user = await _create_user(database)
    auth = AuthService(database.session(), PasswordService())
    login = await auth.login(user.email, "correct horse battery staple")
    assert login is not None

    assert not await auth.change_password(
        login.session_token,
        "correct horse battery staple",
        "correct horse battery staple",
    )
    assert not await auth.change_password(
        login.session_token, "correct horse battery staple", "short"
    )
    assert await auth.current_user(login.session_token) is not None


@pytest.mark.asyncio
async def test_password_change_rejects_inactive_revoked_and_idle_expired_sessions(
    database: Database,
) -> None:
    """Password changes do not trust a session that is no longer usable."""
    auth = AuthService(database.session(), PasswordService())

    inactive_user = await _create_user(database)
    inactive_login = await auth.login(inactive_user.email, "correct horse battery staple")
    assert inactive_login is not None
    await UserRepository(database.session()).set_active(inactive_user.id, False)
    assert not await auth.change_password(
        inactive_login.session_token, "correct horse battery staple", "new inactive password"
    )

    revoked_user = await _create_user(database)
    revoked_login = await auth.login(revoked_user.email, "correct horse battery staple")
    assert revoked_login is not None
    assert await auth.logout(revoked_login.session_token) is None
    assert not await auth.change_password(
        revoked_login.session_token, "correct horse battery staple", "new revoked password"
    )

    expired_user = await _create_user(database)
    expired_login = await auth.login(expired_user.email, "correct horse battery staple")
    assert expired_login is not None
    async with database.transaction() as session:
        stored = await session.get(LoginSession, expired_login.session_id)
        assert stored is not None
        stored.last_seen_at = datetime.now(UTC) - SESSION_IDLE_TIMEOUT
    assert not await auth.change_password(
        expired_login.session_token, "correct horse battery staple", "new expired password"
    )


@pytest.mark.asyncio
async def test_dependencies_enforce_user_admin_and_forced_password_change(
    database: Database,
) -> None:
    """Protected routes require an authenticated admin without a pending password change."""
    user = await _create_user(database, admin=False)
    auth = AuthService(database.session(), PasswordService())
    login = await auth.login(user.email, "correct horse battery staple")
    assert login is not None
    current = await require_user(auth, login.session_token)
    assert current.user_id == user.id
    with pytest.raises(AuthorizationError, match="administrator"):
        await require_admin(auth, login.session_token)

    async with database.transaction() as session:
        stored = await session.get(type(user), user.id)
        assert stored is not None
        stored.force_password_change = True
    with pytest.raises(AuthorizationError, match="password change"):
        await require_user(auth, login.session_token)


@pytest.mark.asyncio
async def test_csrf_validation_requires_the_independent_login_token(database: Database) -> None:
    """Every state-changing route can validate a secret distinct from the session token."""
    user = await _create_user(database)
    auth = AuthService(database.session(), PasswordService())
    login = await auth.login(user.email, "correct horse battery staple")
    assert login is not None

    assert await require_csrf(auth, login.session_token, login.csrf_token) is True
    with pytest.raises(AuthorizationError, match="CSRF"):
        await require_csrf(auth, login.session_token, "wrong token")


@pytest.mark.asyncio
async def test_csrf_validation_rejects_revoked_inactive_and_idle_expired_sessions(
    database: Database,
) -> None:
    """CSRF validation applies the full session lifecycle instead of merely comparing a hash."""
    auth = AuthService(database.session(), PasswordService())

    revoked_user = await _create_user(database)
    revoked = await auth.login(revoked_user.email, "correct horse battery staple")
    assert revoked is not None
    assert await auth.logout(revoked.session_token) is None
    assert await auth.logout("unknown-session-token") is None
    assert not await auth.validate_csrf(revoked.session_token, revoked.csrf_token)

    inactive_user = await _create_user(database)
    inactive = await auth.login(inactive_user.email, "correct horse battery staple")
    assert inactive is not None
    await UserRepository(database.session()).set_active(inactive_user.id, False)
    assert not await auth.validate_csrf(inactive.session_token, inactive.csrf_token)

    expired_user = await _create_user(database)
    expired = await auth.login(expired_user.email, "correct horse battery staple")
    assert expired is not None
    async with database.transaction() as session:
        stored = await session.get(LoginSession, expired.session_id)
        assert stored is not None
        stored.last_seen_at = datetime.now(UTC) - SESSION_IDLE_TIMEOUT
    assert not await auth.validate_csrf(expired.session_token, expired.csrf_token)


@pytest.mark.asyncio
async def test_session_rotation_allows_only_one_concurrent_claim_of_the_old_token(
    database: Database,
) -> None:
    """Concurrent rotation attempts leave one fresh session and never preserve the old bearer."""
    user = await _create_user(database)
    auth = AuthService(database.session(), PasswordService())
    login = await auth.login(user.email, "correct horse battery staple")
    assert login is not None

    first, second = await asyncio.gather(
        auth.rotate_session(login.session_token, login.csrf_token),
        auth.rotate_session(login.session_token, login.csrf_token),
    )

    rotations = [result for result in (first, second) if result is not None]
    assert len(rotations) == 1
    assert await auth.current_user(login.session_token) is None
    assert await auth.current_user(rotations[0].session_token) is not None


@pytest.mark.asyncio
async def test_login_rechecks_password_state_after_async_verification(database: Database) -> None:
    """A password change while Argon2 runs cannot leave an old-password session usable."""

    class PausingPasswordService(PasswordService):
        def __init__(self) -> None:
            super().__init__()
            self.pause = False
            self.verification_started = asyncio.Event()
            self.release_verification = asyncio.Event()

        async def verify_async(self, encoded: str, password: str) -> bool:
            if self.pause:
                self.verification_started.set()
                await self.release_verification.wait()
            return await super().verify_async(encoded, password)

    user = await _create_user(database)
    pausing_passwords = PausingPasswordService()
    contended_auth = AuthService(database.session(), pausing_passwords)
    existing = await contended_auth.login(user.email, "correct horse battery staple")
    assert existing is not None
    pausing_passwords.pause = True

    delayed_login = asyncio.create_task(
        contended_auth.login(user.email, "correct horse battery staple")
    )
    await pausing_passwords.verification_started.wait()
    changing_auth = AuthService(database.session(), PasswordService())
    assert await changing_auth.change_password(
        existing.session_token,
        "correct horse battery staple",
        "a distinct password with 20 chars",
    )
    pausing_passwords.release_verification.set()

    assert await delayed_login is None
    async with database.session()() as session:
        active_sessions = await session.scalar(
            select(func.count())
            .select_from(LoginSession)
            .where(LoginSession.user_id == user.id, LoginSession.revoked_at.is_(None))
        )
    assert active_sessions == 0
