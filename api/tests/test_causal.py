"""Causal ATE + CATE — correct sign, sensible variance-reduction, CI shape."""
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app import causal
from app.db import Recovery, RecoveryStatus, SessionLocal
from app.main import app


async def _seed(mode: str, cohort: str, amt: int, recovered: int):
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id=f"p_{mode}_{cohort}_{amt}_{recovered}",
            razorpay_order_id="o", merchant_customer_id="c",
            amount_paise=amt, currency="INR", cohort=cohort,
            status=RecoveryStatus.RECOVERED.value if recovered else RecoveryStatus.LOST.value,
            recovered_amount_paise=amt if recovered else 0,
            strategy_mode=mode,
        )
        s.add(r); await s.commit()


@pytest.mark.asyncio
async def test_ate_positive_when_agent_beats_naive():
    # Agent: 8/10 recovered on bank_downtime small
    for i in range(10):
        await _seed("agent", "bank_downtime", 30_000, 1 if i < 8 else 0)
    # Naive: 2/10 recovered on bank_downtime small
    for i in range(10):
        await _seed("naive", "bank_downtime", 30_000, 1 if i < 2 else 0)

    async with SessionLocal() as s:
        r = await causal.estimate_ate(s)
    assert r is not None
    assert r.p_agent == 0.8 and r.p_naive == 0.2
    assert 0.5 <= r.ate_raw <= 0.7
    assert 0.5 <= r.ate_stratified <= 0.7
    assert r.ci_low > 0  # significant


@pytest.mark.asyncio
async def test_cate_per_slice_flags_significant_slices():
    # Big lift in one slice
    for i in range(20):
        await _seed("agent", "network_timeout", 30_000, 1 if i < 18 else 0)  # 90%
    for i in range(20):
        await _seed("naive", "network_timeout", 30_000, 1 if i < 4 else 0)   # 20%
    # No lift in another slice
    for i in range(20):
        await _seed("agent", "risk_declined", 30_000, 0)  # 0%
    for i in range(20):
        await _seed("naive", "risk_declined", 30_000, 0)  # 0%

    async with SessionLocal() as s:
        slices = await causal.estimate_cate_per_slice(s, min_per_arm=5)
    nt = next(x for x in slices if x.cohort == "network_timeout")
    rd = next(x for x in slices if x.cohort == "risk_declined")
    assert nt.significant is True
    assert nt.cate >= 0.5
    assert rd.significant is False
    assert rd.cate == 0.0


@pytest.mark.asyncio
async def test_ate_endpoint_and_cate_endpoint():
    for i in range(15):
        await _seed("agent", "insufficient_funds", 30_000, 1 if i < 10 else 0)
    for i in range(15):
        await _seed("naive", "insufficient_funds", 30_000, 1 if i < 2 else 0)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ate = (await c.get("/api/causal/ate")).json()
        cate = (await c.get("/api/causal/cate")).json()
    assert ate["available"] is True
    assert ate["p_agent"] > ate["p_naive"]
    assert ate["ci_low"] > 0
    assert cate["n_slices"] >= 1
    assert cate["n_significant"] >= 1


@pytest.mark.asyncio
async def test_ate_empty_returns_unavailable():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = (await c.get("/api/causal/ate")).json()
    assert r["available"] is False
