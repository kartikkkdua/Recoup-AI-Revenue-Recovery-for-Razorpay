"""Prometheus /metrics endpoint emits valid text-format samples."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Recovery, RecoveryStatus, SessionLocal
from app.main import app


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text_format():
    # Seed a couple of recoveries so we get non-empty gauge samples
    async with SessionLocal() as s:
        for i in range(3):
            s.add(Recovery(
                razorpay_payment_id=f"p_{i}", razorpay_order_id=f"o_{i}",
                merchant_customer_id=f"c_{i}", amount_paise=10_000, currency="INR",
                cohort="bank_downtime",
                status=RecoveryStatus.RECOVERED.value if i < 2 else RecoveryStatus.LOST.value,
                recovered_amount_paise=10_000 if i < 2 else 0,
                strategy_mode="agent", attempts=1, gateway_fee_paise=200,
            ))
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/metrics")
    assert r.status_code == 200
    body = r.text
    # Must include help/type headers and at least one sample of each core metric
    for expected in [
        "# HELP recoup_recoveries_total",
        "# TYPE recoup_recoveries_total gauge",
        "recoup_eligible_amount_paise",
        "recoup_recovered_amount_paise",
        "recoup_gateway_fees_paise",
        "recoup_duplicates_dropped_total",
        "recoup_rate_limit_denials_total",
        "recoup_razorpay_circuit_state",
    ]:
        assert expected in body, f"missing: {expected}"
    # Circuit gauges must sum to 1 (mutually exclusive)
    lines = [l for l in body.splitlines() if l.startswith("recoup_razorpay_circuit_state{")]
    total = sum(float(l.rsplit(" ", 1)[1]) for l in lines)
    assert total == 1.0
