"""Circuit breaker opens after N failures, half-opens after cooldown."""
import asyncio

import pytest

from app.reliability import CircuitBreaker


@pytest.mark.asyncio
async def test_opens_after_threshold():
    cb = CircuitBreaker(fail_threshold=3, open_seconds=60)
    for _ in range(3):
        assert await cb.before_call() is True
        await cb.on_failure()
    assert cb.snapshot()["state"] == "open"
    assert await cb.before_call() is False


@pytest.mark.asyncio
async def test_success_resets_consecutive_failures():
    cb = CircuitBreaker(fail_threshold=3, open_seconds=60)
    await cb.on_failure(); await cb.on_failure()
    await cb.on_success()
    assert cb.snapshot()["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_half_open_after_cooldown():
    cb = CircuitBreaker(fail_threshold=2, open_seconds=0.05)
    await cb.on_failure(); await cb.on_failure()
    assert cb.snapshot()["state"] == "open"
    await asyncio.sleep(0.1)
    assert await cb.before_call() is True
    assert cb.snapshot()["state"] == "half_open"
