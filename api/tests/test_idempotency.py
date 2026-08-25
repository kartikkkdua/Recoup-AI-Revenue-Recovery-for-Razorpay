"""Duplicate webhooks must never create duplicate recoveries or double-charge."""
import asyncio
import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.db import SessionLocal, WebhookEvent, init_db
from app.main import app
from sqlalchemy import select


def _sign(body: bytes) -> str:
    return hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_duplicate_event_id_rejected_as_duplicate():
    await init_db()
    payload = {
        "id": "evt_test_dup_1",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {"payment": {"entity": {"id": "pay_x", "order_id": "o_x", "amount": 100,
                                            "currency": "INR",
                                            "error_code": "BAD_REQUEST_ERROR",
                                            "error_reason": "insufficient_funds",
                                            "error_description": "no balance"}}},
    }
    body = json.dumps(payload).encode()
    sig = _sign(body)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post("/webhooks", content=body,
                               headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})
        r2 = await client.post("/webhooks", content=body,
                               headers={"X-Razorpay-Signature": sig, "content-type": "application/json"})

    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"
    assert r2.status_code == 200
    assert r2.json()["status"] == "duplicate"

    async with SessionLocal() as s:
        rows = (await s.scalars(select(WebhookEvent).where(WebhookEvent.razorpay_event_id == "evt_test_dup_1"))).all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_bad_signature_rejected():
    payload = {"id": "evt_test_badsig", "event": "payment.failed", "payload": {}}
    body = json.dumps(payload).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/webhooks", content=body,
                              headers={"X-Razorpay-Signature": "deadbeef", "content-type": "application/json"})
    assert r.status_code == 401
