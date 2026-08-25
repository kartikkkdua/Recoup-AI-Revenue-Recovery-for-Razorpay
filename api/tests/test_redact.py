"""PII redaction — emails, phones, cards masked in default responses."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Recovery, RecoveryStatus, SessionLocal
from app.main import app
from app.redact import redact_str


def test_redact_email():
    assert redact_str("kartikcodespaces@gmail.com").startswith("k***")


def test_redact_phone():
    r = redact_str("+919528989520")
    assert "9528" not in r and r.endswith("20")


def test_redact_card():
    assert redact_str("4111 1111 1111 1111") == "4111-****-****-1111"


@pytest.mark.asyncio
async def test_recovery_detail_redacts_by_default_but_not_with_header():
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id="pay_pii", razorpay_order_id="o_pii",
            merchant_customer_id="c_pii", amount_paise=100, currency="INR",
            cohort="card_declined", status=RecoveryStatus.IN_PROGRESS.value,
            original_error_description="sent to kartikcodespaces@gmail.com and +919528989520",
        )
        s.add(r); await s.commit(); await s.refresh(r); rid = r.id

        # Add an audit entry containing PII
        from app.db import AuditEntry
        s.add(AuditEntry(recovery_id=rid, step="test", actor="test",
                         detail={"contact": "+919528989520", "email": "kartikcodespaces@gmail.com"}))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        redacted = (await c.get(f"/api/recoveries/{rid}")).json()
        raw = (await c.get(f"/api/recoveries/{rid}", headers={"X-Show-PII": "1"})).json()

    assert redacted["pii_redacted"] is True
    assert raw["pii_redacted"] is False
    a_red = next(a for a in redacted["audit"] if a["step"] == "test")
    a_raw = next(a for a in raw["audit"] if a["step"] == "test")
    assert "kartikcodespaces" not in str(a_red["detail"])
    assert "kartikcodespaces" in str(a_raw["detail"])
