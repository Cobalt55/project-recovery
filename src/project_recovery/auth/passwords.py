"""Argon2id password hashing with bounded asynchronous worker execution."""

import asyncio
import hmac
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

MAX_PASSWORD_LENGTH = 1024
MIN_REPLACEMENT_PASSWORD_LENGTH = 20
PASSWORD_WORK_LIMIT = 4
_PASSWORD_WORK_EXECUTOR = ThreadPoolExecutor(
    max_workers=PASSWORD_WORK_LIMIT,
    thread_name_prefix="project-recovery-argon",
)


class _PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, encoded: str, password: str) -> bool: ...

    def check_needs_rehash(self, encoded: str) -> bool: ...


class PasswordService:
    """Hash and verify local passwords without blocking the async request loop."""

    _production_hasher = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    _dummy_hash = _production_hasher.hash("project-recovery-dummy-password")

    def __init__(
        self,
        hasher: _PasswordHasher | None = None,
        work_limit: int = PASSWORD_WORK_LIMIT,
        work_limiter: threading.BoundedSemaphore | None = None,
    ) -> None:
        if work_limit < 1:
            raise ValueError("password work limit must be positive")
        self._hasher = hasher or self._production_hasher
        self._work_limiter = work_limiter or threading.BoundedSemaphore(work_limit)

    def hash(self, password: str) -> str:
        """Return an Argon2id hash for bootstrap and other synchronous callers."""
        self._validate(password)
        return self._hasher.hash(password)

    async def hash_async(self, password: str) -> str:
        """Hash a permitted password in the bounded worker pool."""
        self._validate(password)
        return cast(str, await self._run(self._hasher.hash, password))

    def verify(self, encoded: str, password: str) -> bool:
        """Return false for wrong, malformed, or unsuitable credential input."""
        if not self._is_permitted(password):
            return False
        try:
            return self._hasher.verify(encoded, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    async def verify_async(self, encoded: str, password: str) -> bool:
        """Verify a password in the bounded worker pool."""
        if not self._is_permitted(password):
            return False
        return cast(bool, await self._run(self.verify, encoded, password))

    def needs_rehash(self, encoded: str) -> bool:
        """Identify valid legacy hashes that should migrate after a successful login."""
        try:
            return self._hasher.check_needs_rehash(encoded)
        except (InvalidHashError, VerificationError):
            return False

    async def needs_rehash_async(self, encoded: str) -> bool:
        """Check legacy hash parameters without blocking the request loop."""
        return cast(bool, await self._run(self.needs_rehash, encoded))

    def verify_dummy(self, password: str) -> None:
        """Consume comparable hash work when an account cannot be authenticated."""
        self.verify(self._dummy_hash, password)

    async def verify_dummy_async(self, password: str) -> None:
        """Run unknown-user timing equalization in the bounded worker pool."""
        await self._run(self.verify_dummy, password)

    def is_acceptable_replacement(self, current_password: str, new_password: str) -> bool:
        """Require a distinct replacement that meets the temporary-credential baseline."""
        return (
            len(new_password) >= MIN_REPLACEMENT_PASSWORD_LENGTH
            and self._is_permitted(new_password)
            and not hmac.compare_digest(current_password, new_password)
        )

    async def _run(self, operation: Callable[..., object], *args: str) -> object:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _PASSWORD_WORK_EXECUTOR, self._run_limited, operation, *args
        )

    def _run_limited(self, operation: Callable[..., object], *args: str) -> object:
        """Execute in the dedicated Argon pool under the optional local capacity limit."""
        with self._work_limiter:
            return operation(*args)

    @staticmethod
    def _is_permitted(password: str) -> bool:
        return bool(password) and len(password) <= MAX_PASSWORD_LENGTH

    def _validate(self, password: str) -> None:
        if not self._is_permitted(password):
            raise ValueError("password must be non-empty and at most 1024 characters")


_shared_password_service = PasswordService()


def shared_password_service() -> PasswordService:
    """Return the process-wide password service and its shared concurrency bound."""
    return _shared_password_service
