"""Cohort-mix drift flags cohorts whose share shifted >=10pp with severity."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.db import Recovery, RecoveryStatus, SessionLocal
from app.main import app


async def _seed(cohort: str, when: datetime, n: int) -> None:
    async with SessionLocal() as s:
        for i in range(n):
            r = Recovery(
                razorpay_payment_id=f"p_{cohort}_{i}", razorpay_order_id=f"o_{cohort}_{i}",
                merchant_customer_id=f"c_{cohort}_{i}", amount_paise=100, currency="INR",
                cohort=cohort, status=RecoveryStatus.IN_PROGRESS.value, strategy_mode="agent",
                created_at=when,
            )
            s.add(r)
        await s.commit()


@pytest.mark.asyncio
async def test_flags_cohort_that_spikes_in_recent_window():
    now = datetime.now(timezone.utc)
    baseline_at = now - timedelta(hours=48)
    recent_at = now - timedelta(minutes=30)

    # Baseline: 10 each of two cohorts (bank_downtime 20%, network_timeout 20%)
    await _seed("bank_downtime", baseline_at, 10)
    await _seed("network_timeout", baseline_at, 10)
    await _seed("insufficient_funds", baseline_at, 30)  # 60% baseline

    # Recent window (6h): bank_downtime spikes to 80% share
    await _seed("bank_downtime", recent_at, 40)
    await _seed("insufficient_funds", recent_at, 10)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/drift")
    alerts = r.json()["alerts"]
    bd = next(a for a in alerts if a["cohort"] == "bank_downtime")
    assert bd["delta_pp"] > 0.10
    assert bd["severity"] in {"warn", "critical"}
    assert bd["recent_count"] == 40


@pytest.mark.asyncio
async def test_no_alerts_when_recent_window_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/metrics/drift")
    body = r.json()
    assert body["alerts"] == []
    assert "too small" in body.get("reason", "")
