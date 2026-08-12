"""Small process-local pre-authentication throttle with bounded state."""

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta

MAX_TRACKED_KEYS = 10_000


class LoginRateLimiter:
    """Throttle repeated failures by normalized account and client address."""

    def __init__(
        self,
        *,
        account_limit: int = 5,
        ip_limit: int = 20,
        window: timedelta = timedelta(minutes=15),
    ) -> None:
        self._account_limit = max(1, account_limit)
        self._ip_limit = max(1, ip_limit)
        self._window = window
        self._attempts: dict[tuple[str, str], deque[datetime]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(
        self, client_address: str, email: str, *, now: datetime | None = None
    ) -> bool:
        """Return whether both the address and account remain below their limits."""
        checked_at = now or datetime.now(UTC)
        async with self._lock:
            account = self._pruned(("account", _account(email)), checked_at)
            address = self._pruned(("address", _address(client_address)), checked_at)
            return len(account) < self._account_limit and len(address) < self._ip_limit

    async def record_failure(
        self, client_address: str, email: str, *, now: datetime | None = None
    ) -> None:
        """Record one generic login failure without retaining credential material."""
        checked_at = now or datetime.now(UTC)
        async with self._lock:
            self._pruned(("account", _account(email)), checked_at).append(checked_at)
            self._pruned(("address", _address(client_address)), checked_at).append(checked_at)
            while len(self._attempts) > MAX_TRACKED_KEYS:
                self._attempts.pop(next(iter(self._attempts)))

    async def record_success(self, client_address: str, email: str) -> None:
        """Clear the successful account while retaining address-wide abuse pressure."""
        del client_address
        async with self._lock:
            self._attempts.pop(("account", _account(email)), None)

    def _pruned(self, key: tuple[str, str], now: datetime) -> deque[datetime]:
        attempts = self._attempts.setdefault(key, deque())
        cutoff = now - self._window
        while attempts and attempts[0] <= cutoff:
            attempts.popleft()
        if not attempts:
            self._attempts.pop(key, None)
            attempts = self._attempts.setdefault(key, deque())
        return attempts


def _account(email: str) -> str:
    return email.strip().casefold()[:320]


def _address(value: str) -> str:
    return value.strip()[:128] or "unknown"


__all__ = ["LoginRateLimiter"]
