"""Feature store computes LTV, streak, preferred rail from Recovery history."""
from datetime import datetime, timedelta, timezone

import pytest

from app import features as features_mod
from app.db import Recovery, RecoveryStatus, SessionLocal


async def _seed(customer: str, *, status: str, amt: int, rec: int, rail: str = "upi", when=None):
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id=f"p_{customer}_{amt}_{status}",
            razorpay_order_id="o", merchant_customer_id=customer,
            amount_paise=amt, currency="INR", cohort="card_declined",
            status=status, recovered_amount_paise=rec, strategy_mode="agent",
            strategy={"rails": [rail]},
            created_at=(when or datetime.now(timezone.utc)),
        )
        s.add(r); await s.commit()


@pytest.mark.asyncio
async def test_ltv_sums_only_recovered():
    await _seed("cust_A", status=RecoveryStatus.RECOVERED.value, amt=50000, rec=50000)
    await _seed("cust_A", status=RecoveryStatus.RECOVERED.value, amt=20000, rec=20000)
    await _seed("cust_A", status=RecoveryStatus.LOST.value, amt=99999, rec=0)
    async with SessionLocal() as s:
        f = await features_mod.compute_features(
            s, customer_id="cust_A", cohort="card_declined", amount_paise=10000)
    assert f.customer_ltv_paise == 70000


@pytest.mark.asyncio
async def test_failure_streak_counts_consecutive_recent_failures():
    now = datetime.now(timezone.utc)
    # 3 recent failures (LOST), then an old win
    for i in range(3):
        await _seed("cust_S", status=RecoveryStatus.LOST.value, amt=100, rec=0,
                    when=now - timedelta(minutes=i))
    await _seed("cust_S", status=RecoveryStatus.RECOVERED.value, amt=100, rec=100,
                when=now - timedelta(hours=1))
    async with SessionLocal() as s:
        f = await features_mod.compute_features(
            s, customer_id="cust_S", cohort="card_declined", amount_paise=100)
    assert f.customer_failure_streak == 3


@pytest.mark.asyncio
async def test_preferred_rail_picks_most_common_success_rail():
    await _seed("cust_R", status=RecoveryStatus.RECOVERED.value, amt=100, rec=100, rail="upi")
    await _seed("cust_R", status=RecoveryStatus.RECOVERED.value, amt=100, rec=100, rail="upi")
    await _seed("cust_R", status=RecoveryStatus.RECOVERED.value, amt=100, rec=100, rail="card")
    async with SessionLocal() as s:
        f = await features_mod.compute_features(
            s, customer_id="cust_R", cohort="card_declined", amount_paise=100)
    assert f.customer_preferred_rail == "upi"


@pytest.mark.asyncio
async def test_no_customer_id_returns_zeros():
    async with SessionLocal() as s:
        f = await features_mod.compute_features(
            s, customer_id=None, cohort="card_declined", amount_paise=100)
    assert f.customer_ltv_paise == 0
    assert f.customer_failure_streak == 0
    assert f.customer_preferred_rail is None


@pytest.mark.asyncio
async def test_high_value_flag_and_ticket_bucket():
    async with SessionLocal() as s:
        low = await features_mod.compute_features(
            s, customer_id=None, cohort="card_declined", amount_paise=40_000)
        high = await features_mod.compute_features(
            s, customer_id=None, cohort="card_declined", amount_paise=600_000)
    assert low.ticket_bucket == "small" and not low.is_high_value
    assert high.ticket_bucket == "large" and high.is_high_value
