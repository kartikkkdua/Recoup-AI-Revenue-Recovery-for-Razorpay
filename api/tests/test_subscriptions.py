"""Subscriptions endpoint filters to subscription-tagged recoveries only."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Recovery, RecoveryStatus, SessionLocal
from app.main import app


async def _seed(sub_id: str | None, status: str, recovered: int, amount: int) -> int:
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id="pay_x", razorpay_order_id="o_x",
            razorpay_subscription_id=sub_id,
            merchant_customer_id="c_x", amount_paise=amount, currency="INR",
            cohort="auth_expired", status=status, recovered_amount_paise=recovered,
        )
        s.add(r); await s.commit(); await s.refresh(r); return r.id


@pytest.mark.asyncio
async def test_summary_ignores_non_subscription_recoveries():
    await _seed(None, RecoveryStatus.RECOVERED.value, 100_00, 100_00)  # non-sub, ignored
    await _seed("sub_1", RecoveryStatus.RECOVERED.value, 500_00, 500_00)
    await _seed("sub_2", RecoveryStatus.LOST.value, 0, 300_00)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/subscriptions/summary")
    body = r.json()
    assert body["counts"]["total"] == 2
    assert body["counts"]["recovered"] == 1
    assert body["counts"]["churned"] == 1
    assert body["mrr_at_risk_paise"] == 800_00
    assert body["mrr_retained_paise"] == 500_00
    assert body["annualised_mrr_retained_paise"] == 500_00 * 12


@pytest.mark.asyncio
async def test_list_returns_only_subscription_rows():
    await _seed(None, RecoveryStatus.RECOVERED.value, 100, 100)
    rid = await _seed("sub_only", RecoveryStatus.RECOVERED.value, 900_00, 900_00)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/subscriptions?limit=50")
    items = r.json()["items"]
    assert all(i["subscription_id"] for i in items)
    assert any(i["id"] == rid for i in items)
