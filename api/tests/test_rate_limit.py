"""Per-customer rate limiter blocks the Nth+1 attempt inside the window."""
import pytest

from app.reliability import CustomerRateLimiter


@pytest.mark.asyncio
async def test_allows_up_to_cap_then_denies():
    rl = CustomerRateLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        allowed, remaining = await rl.check_and_record("cust_a")
        assert allowed is True
    allowed, remaining = await rl.check_and_record("cust_a")
    assert allowed is False
    assert remaining == 0
    assert rl.snapshot()["denials_total"] == 1


@pytest.mark.asyncio
async def test_no_customer_id_always_allowed():
    rl = CustomerRateLimiter(max_attempts=1, window_seconds=60)
    for _ in range(10):
        allowed, _ = await rl.check_and_record(None)
        assert allowed is True
    assert rl.snapshot()["denials_total"] == 0


@pytest.mark.asyncio
async def test_separate_customers_have_separate_buckets():
    rl = CustomerRateLimiter(max_attempts=2, window_seconds=60)
    for cust in ["cust_a", "cust_b", "cust_c"]:
        for _ in range(2):
            allowed, _ = await rl.check_and_record(cust)
            assert allowed is True
    assert rl.snapshot()["customers_tracked"] == 3
    assert rl.snapshot()["denials_total"] == 0
