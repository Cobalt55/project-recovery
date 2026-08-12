"""Argon2id password hashing with safe verification failures."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

MAX_PASSWORD_LENGTH = 1024


class PasswordService:
    """Hash and verify local passwords without ever retaining plaintext values."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash("project-recovery-dummy-password")

    def hash(self, password: str) -> str:
        """Return an Argon2id hash for a permitted non-empty password."""
        self._validate(password)
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        """Return false for wrong, malformed, or unsuitable credential input."""
        if not self._is_permitted(password):
            return False
        try:
            return self._hasher.verify(encoded, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        """Identify valid legacy hashes that should migrate after a successful login."""
        try:
            return self._hasher.check_needs_rehash(encoded)
        except (InvalidHashError, VerificationError):
            return False

    def verify_dummy(self, password: str) -> None:
        """Consume comparable hash work when an account cannot be authenticated."""
        self.verify(self._dummy_hash, password)

    @staticmethod
    def _is_permitted(password: str) -> bool:
        return bool(password) and len(password) <= MAX_PASSWORD_LENGTH

    def _validate(self, password: str) -> None:
        if not self._is_permitted(password):
            raise ValueError("password must be non-empty and at most 1024 characters")
