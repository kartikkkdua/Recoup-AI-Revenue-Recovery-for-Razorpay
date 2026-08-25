"""ROI estimator returns non-degenerate numbers and honors input scaling."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


async def _post(body: dict) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/roi/estimate", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_lift_positive_and_scales_with_volume():
    a = await _post({"monthly_failed_txns": 1000, "avg_ticket_rupees": 500, "subscription_share_pct": 0})
    b = await _post({"monthly_failed_txns": 2000, "avg_ticket_rupees": 500, "subscription_share_pct": 0})
    assert a["monthly"]["lift_paise"] > 0
    # ~2x volume ⇒ ~2x lift (allow ±10% for cohort-mix rounding)
    ratio = b["monthly"]["lift_paise"] / a["monthly"]["lift_paise"]
    assert 1.9 <= ratio <= 2.1


@pytest.mark.asyncio
async def test_subscription_weighting_increases_annual_lift_only():
    """Monthly recovery is capped by monthly eligible; the LTV bonus for
    subscriptions only compounds over the year, so annual lift should grow
    with subscription share while monthly does not."""
    base = await _post({"monthly_failed_txns": 1000, "avg_ticket_rupees": 500, "subscription_share_pct": 0})
    heavy = await _post({"monthly_failed_txns": 1000, "avg_ticket_rupees": 500, "subscription_share_pct": 100})
    assert heavy["monthly"]["lift_paise"] == base["monthly"]["lift_paise"]
    assert heavy["annual"]["lift_paise"] > base["annual"]["lift_paise"]
    # 100% subs → 1 + 100/100 * 2 = 3x bonus
    assert heavy["rates"]["sub_ltv_bonus_multiplier"] == 3.0


@pytest.mark.asyncio
async def test_defaults_endpoint_returns_full_cohort_mix():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/roi/defaults")
    assert r.status_code == 200
    body = r.json()
    assert len(body["mix"]) == 8
    assert all("cohort" in m and "agent_recovery_rate" in m for m in body["mix"])
