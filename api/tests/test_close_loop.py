"""payment_link.paid and payment.captured close the matching recovery."""
import pytest
from sqlalchemy import select

from app.closer import handle_close_event
from app.db import Recovery, RecoveryStatus, SessionLocal


async def _seed_recovery(*, ref: str) -> int:
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id="pay_orig", razorpay_order_id="order_orig",
            razorpay_recovery_ref=ref,
            merchant_customer_id="cust_z", amount_paise=49900,
            currency="INR", cohort="card_declined",
            status=RecoveryStatus.IN_PROGRESS.value,
        )
        s.add(r); await s.commit(); await s.refresh(r)
        return r.id


@pytest.mark.asyncio
async def test_payment_link_paid_closes_recovery():
    rid = await _seed_recovery(ref="plink_test_abc")
    result = await handle_close_event("payment_link.paid", {
        "payload": {
            "payment_link": {"entity": {"id": "plink_test_abc", "amount": 49900, "status": "paid"}},
            "payment": {"entity": {"id": "pay_new", "amount": 49900}},
        }
    })
    assert result.get("closed") == rid

    async with SessionLocal() as s:
        r = await s.get(Recovery, rid)
        assert r.status == RecoveryStatus.RECOVERED.value
        assert r.recovered_amount_paise == 49900


@pytest.mark.asyncio
async def test_payment_captured_closes_recovery():
    rid = await _seed_recovery(ref="order_retry_xyz")
    result = await handle_close_event("payment.captured", {
        "payload": {"payment": {"entity": {
            "id": "pay_new2", "order_id": "order_retry_xyz", "amount": 49900,
        }}}
    })
    assert result.get("closed") == rid


@pytest.mark.asyncio
async def test_refund_retracts_recovery():
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id="pay_toRefund", razorpay_order_id="o",
            merchant_customer_id="c", amount_paise=10000, currency="INR",
            cohort="network_timeout", status=RecoveryStatus.RECOVERED.value,
            recovered_amount_paise=10000,
        )
        s.add(r); await s.commit(); await s.refresh(r); rid = r.id
    result = await handle_close_event("refund.processed", {
        "payload": {"refund": {"entity": {
            "id": "rfnd_1", "payment_id": "pay_toRefund", "amount": 10000,
        }}}
    })
    assert result.get("retracted") == rid
    async with SessionLocal() as s:
        r = await s.get(Recovery, rid)
        assert r.status == RecoveryStatus.LOST.value
        assert r.recovered_amount_paise == 0


@pytest.mark.asyncio
async def test_unknown_close_event_ignored():
    result = await handle_close_event("payment.something.weird", {"payload": {}})
    assert result == {"ignored": "payment.something.weird"}
