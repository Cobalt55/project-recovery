"""Security behavior for local password handling."""

import asyncio
import threading

import pytest

from project_recovery.auth.passwords import PASSWORD_WORK_LIMIT, PasswordService
from project_recovery.auth.routes import CookiePolicy
from project_recovery.auth.sessions import LoginResult, token_hash


@pytest.fixture
def password_service() -> PasswordService:
    """Use the production Argon2id configuration."""
    return PasswordService()


def test_password_hash_is_argon2id(password_service: PasswordService) -> None:
    """Passwords are one-way Argon2id hashes, never reversible values."""
    encoded = password_service.hash("correct horse battery staple")

    assert encoded.startswith("$argon2id$")
    assert password_service.verify(encoded, "correct horse battery staple")


def test_password_rejects_mismatch_malformed_empty_and_overlong(
    password_service: PasswordService,
) -> None:
    """Invalid credential input gets one safe failure result."""
    encoded = password_service.hash("correct horse battery staple")

    assert not password_service.verify(encoded, "not the password")
    assert not password_service.verify("not an argon2 hash", "correct horse battery staple")
    assert not password_service.verify(encoded, "")
    with pytest.raises(ValueError, match="password"):
        password_service.hash("x" * 1025)


def test_password_service_reports_when_an_older_hash_needs_rehash(
    password_service: PasswordService,
) -> None:
    """Successful verification can request migration to current parameters."""
    encoded = password_service.hash("correct horse battery staple")

    assert password_service.needs_rehash(encoded) is False


def test_session_and_csrf_tokens_are_stored_as_nonrecoverable_hashes() -> None:
    """Raw bearer material is never the persisted representation."""
    token = "a session token"

    assert token_hash(token) != token
    assert len(token_hash(token)) == 64


def test_production_cookie_policy_keeps_session_cookie_secure_and_http_only() -> None:
    """The session cookie has browser protections in production deployments."""
    policy = CookiePolicy.for_environment("production")

    assert policy.session.secure is True
    assert policy.session.http_only is True
    assert policy.session.same_site == "lax"
    assert policy.session.path == "/"
    assert policy.csrf.http_only is False


def test_login_result_repr_redacts_raw_bearer_values() -> None:
    """A diagnostic representation cannot leak reusable browser credentials."""
    result = LoginResult(
        session_id="safe-id",  # type: ignore[arg-type]
        session_token="session-secret-that-must-not-appear",
        csrf_token="csrf-secret-that-must-not-appear",
    )

    representation = repr(result)

    assert "safe-id" in representation
    assert "session-secret-that-must-not-appear" not in representation
    assert "csrf-secret-that-must-not-appear" not in representation


def test_password_change_rejects_a_reused_or_short_replacement(
    password_service: PasswordService,
) -> None:
    """Temporary bootstrap credentials cannot remain a password after a forced change."""
    current = "temporary-bootstrap-password"

    assert password_service.is_acceptable_replacement(current, current) is False
    assert password_service.is_acceptable_replacement(current, "too short") is False
    assert password_service.is_acceptable_replacement(current, "replacement-password-123") is True


def test_async_password_verification_offloads_and_respects_the_shared_bound() -> None:
    """Concurrent authentication work leaves the event loop runnable and is bounded."""

    class BlockingHasher:
        def __init__(self) -> None:
            self.started = threading.Event()
            self.release = threading.Event()
            self.active = 0
            self.maximum_active = 0
            self.lock = threading.Lock()

        def verify(self, _encoded: str, _password: str) -> bool:
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                self.started.set()
            self.release.wait(timeout=1)
            with self.lock:
                self.active -= 1
            return True

    async def exercise() -> int:
        hasher = BlockingHasher()
        service = PasswordService(hasher=hasher, work_limit=1)
        first = asyncio.create_task(service.verify_async("encoded", "password"))
        await asyncio.to_thread(hasher.started.wait, 1)
        second = asyncio.create_task(service.verify_async("encoded", "password"))
        await asyncio.sleep(0)
        assert not second.done()
        hasher.release.set()
        assert await first is True
        assert await second is True
        return hasher.maximum_active

    assert asyncio.run(exercise()) == 1


def test_async_password_work_is_bounded_across_service_instances() -> None:
    """Creating services cannot multiply the process-wide Argon2 worker allowance."""

    class BlockingHasher:
        def __init__(self) -> None:
            self.enough_started = threading.Event()
            self.release = threading.Event()
            self.active = 0
            self.maximum_active = 0
            self.lock = threading.Lock()

        def verify(self, _encoded: str, _password: str) -> bool:
            with self.lock:
                self.active += 1
                self.maximum_active = max(self.maximum_active, self.active)
                if self.active >= PASSWORD_WORK_LIMIT:
                    self.enough_started.set()
            self.release.wait(timeout=1)
            with self.lock:
                self.active -= 1
            return True

    async def exercise() -> int:
        hasher = BlockingHasher()
        services = [PasswordService(hasher=hasher) for _ in range(PASSWORD_WORK_LIMIT + 1)]
        tasks = [
            asyncio.create_task(service.verify_async("encoded", "password")) for service in services
        ]
        await asyncio.to_thread(hasher.enough_started.wait, 1)
        await asyncio.sleep(0)
        hasher.release.set()
        assert all(await asyncio.gather(*tasks))
        return hasher.maximum_active

    assert asyncio.run(exercise()) == PASSWORD_WORK_LIMIT
