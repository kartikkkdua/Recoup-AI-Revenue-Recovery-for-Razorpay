"""T-learner uplift model — trains from history, predicts sane ITE, gates intervention."""
import pytest
from httpx import ASGITransport, AsyncClient

from app import uplift
from app.db import Recovery, RecoveryStatus, SessionLocal
from app.main import app


async def _seed_recovery(mode: str, cohort: str, amt: int, recovered: bool):
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
async def test_train_returns_none_without_enough_data():
    async with SessionLocal() as s:
        m = await uplift.train(s, min_per_arm=30)
    assert m is None
    assert uplift.snapshot() is None


@pytest.mark.asyncio
async def test_train_then_predict_positive_ite_for_helped_cohort():
    # 40 agent bank_downtime successes, 40 naive bank_downtime failures
    for i in range(40):
        await _seed_recovery("agent", "bank_downtime", 30_000, recovered=i < 32)  # 80%
        await _seed_recovery("naive", "bank_downtime", 30_000, recovered=i < 8)   # 20%
    async with SessionLocal() as s:
        m = await uplift.train(s, min_per_arm=30, threshold=0.05)
    assert m is not None
    p = uplift.predict(cohort="bandit_downtime" if False else "bank_downtime",
                       amount_paise=30_000)
    assert p is not None
    assert p.p_agent > p.p_naive
    assert p.ite > 0.20  # sensible positive lift
    assert p.should_intervene is True


@pytest.mark.asyncio
async def test_predict_returns_none_when_untrained():
    # Explicitly reset module state
    uplift._model = None
    p = uplift.predict(cohort="bank_downtime", amount_paise=30_000)
    assert p is None


@pytest.mark.asyncio
async def test_train_and_predict_endpoints_round_trip():
    for i in range(40):
        await _seed_recovery("agent", "network_timeout", 30_000, recovered=i < 30)
        await _seed_recovery("naive", "network_timeout", 30_000, recovered=i < 4)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        train_r = await c.post("/api/uplift/train?threshold=0.05&min_per_arm=30")
        assert train_r.status_code == 200
        status_r = await c.get("/api/uplift/status")
        assert status_r.json()["trained"] is True
        pred_r = await c.get("/api/uplift/predict?cohort=network_timeout&amount_paise=30000")
        assert pred_r.status_code == 200
        pred = pred_r.json()
        assert pred["p_agent"] > pred["p_naive"]
        assert pred["should_intervene"] is True


@pytest.mark.asyncio
async def test_predict_endpoint_untrained_returns_409():
    uplift._model = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/uplift/predict?cohort=bank_downtime&amount_paise=100")
    assert r.status_code == 409
