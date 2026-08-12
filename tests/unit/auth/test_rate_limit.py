"""Login throttling contract tests."""

from datetime import UTC, datetime, timedelta

import pytest

from project_recovery.auth.rate_limit import LoginRateLimiter


@pytest.mark.asyncio
async def test_account_failures_are_bounded_and_expire() -> None:
    limiter = LoginRateLimiter(account_limit=3, ip_limit=10, window=timedelta(minutes=10))
    now = datetime(2026, 8, 12, tzinfo=UTC)

    for _ in range(3):
        assert await limiter.is_allowed("203.0.113.1", " User@Example.test ", now=now)
        await limiter.record_failure("203.0.113.1", " User@Example.test ", now=now)

    assert not await limiter.is_allowed("203.0.113.1", "user@example.test", now=now)
    assert await limiter.is_allowed(
        "203.0.113.1",
        "user@example.test",
        now=now + timedelta(minutes=10, seconds=1),
    )


@pytest.mark.asyncio
async def test_ip_limit_spans_accounts_and_success_clears_only_account_failures() -> None:
    limiter = LoginRateLimiter(account_limit=2, ip_limit=3)
    now = datetime(2026, 8, 12, tzinfo=UTC)

    await limiter.record_failure("203.0.113.2", "first@example.test", now=now)
    await limiter.record_failure("203.0.113.2", "first@example.test", now=now)
    await limiter.record_success("203.0.113.2", "first@example.test")

    assert await limiter.is_allowed("203.0.113.2", "first@example.test", now=now)
    await limiter.record_failure("203.0.113.2", "second@example.test", now=now)
    assert not await limiter.is_allowed("203.0.113.2", "third@example.test", now=now)
