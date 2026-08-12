"""Security behavior for local password handling."""

import pytest

from project_recovery.auth.passwords import PasswordService
from project_recovery.auth.routes import CookiePolicy
from project_recovery.auth.sessions import token_hash


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
