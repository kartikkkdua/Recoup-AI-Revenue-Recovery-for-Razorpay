"""Chaos test — inject Razorpay API failures, prove circuit breaker opens
and subsequent calls are refused with CircuitOpenError (not silent errors)."""
import pytest

from app.reliability import CircuitBreaker
from app.razorpay_client import CircuitOpenError, RazorpayClient
from app import razorpay_client as rc_module


@pytest.mark.asyncio
async def test_circuit_opens_after_repeated_razorpay_failures(monkeypatch):
    cb = CircuitBreaker(fail_threshold=3, open_seconds=60)
    monkeypatch.setattr(rc_module, "razorpay_circuit", cb)

    client = RazorpayClient()

    class ExplodingSDK:
        class payment_link:
            @staticmethod
            def create(_): raise RuntimeError("simulated razorpay 5xx")
        class order:
            @staticmethod
            def create(_): raise RuntimeError("simulated razorpay 5xx")

    monkeypatch.setattr(client, "sandbox", False)
    monkeypatch.setattr(client, "_client", ExplodingSDK)

    # 3 sequential real-mode calls should fail with the underlying RuntimeError
    for i in range(3):
        with pytest.raises(RuntimeError):
            await client.create_payment_link(
                amount_paise=100, currency="INR",
                customer={"contact": "+91", "email": "x@y", "name": "n"},
                simulated=False,
            )
    # Circuit is now open — 4th call refused fast with CircuitOpenError
    assert cb.snapshot()["state"] == "open"
    with pytest.raises(CircuitOpenError):
        await client.create_payment_link(
            amount_paise=100, currency="INR",
            customer={"contact": "+91", "email": "x@y", "name": "n"},
            simulated=False,
        )


@pytest.mark.asyncio
async def test_circuit_recovers_after_success(monkeypatch):
    """After a real success in half-open, breaker closes and calls flow again."""
    cb = CircuitBreaker(fail_threshold=2, open_seconds=0.05)
    monkeypatch.setattr(rc_module, "razorpay_circuit", cb)
    client = RazorpayClient()

    class SDK:
        _fail_count = 0
        class order:
            @staticmethod
            def create(_):
                SDK._fail_count += 1
                if SDK._fail_count <= 2:
                    raise RuntimeError("boom")
                return {"id": "order_recovered", "amount": 100, "status": "created"}

    monkeypatch.setattr(client, "sandbox", False)
    monkeypatch.setattr(client, "_client", SDK)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await client.retry_order(order_id="o", amount_paise=100, simulated=False)
    assert cb.snapshot()["state"] == "open"

    import asyncio
    await asyncio.sleep(0.1)  # cooldown → half_open
    result = await client.retry_order(order_id="o", amount_paise=100, simulated=False)
    assert result["id"] == "order_recovered"
    assert cb.snapshot()["state"] == "closed"
