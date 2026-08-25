"""Tier A + B: AIPW, OPE, mSPRT, JS drift, conformal — end-to-end."""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app import bandit as bandit_mod
from app import causal_dr, conformal, drift_kl, ope, sequential, uplift
from app.db import BanditArm, Recovery, RecoveryStatus, SessionLocal
from app.main import app


async def _seed(mode, cohort, amt, recovered, action="retry", when=None):
    async with SessionLocal() as s:
        r = Recovery(
            razorpay_payment_id=f"p_{mode}_{cohort}_{amt}_{recovered}_{action}_{when}",
            razorpay_order_id="o", merchant_customer_id="c",
            amount_paise=amt, currency="INR", cohort=cohort,
            status=RecoveryStatus.RECOVERED.value if recovered else RecoveryStatus.LOST.value,
            recovered_amount_paise=amt if recovered else 0,
            strategy_mode=mode, strategy={"action": action},
            created_at=(when or datetime.now(timezone.utc)),
        )
        s.add(r); await s.commit()


# ---------- AIPW ----------

@pytest.mark.asyncio
async def test_aipw_positive_and_ci_shape():
    for i in range(40):
        await _seed("agent", "bank_downtime", 30_000, i < 32)  # 80%
        await _seed("naive", "bank_downtime", 30_000, i < 8)   # 20%
    async with SessionLocal() as s:
        r = await causal_dr.estimate_aipw(s, min_per_arm=20)
    assert r is not None
    assert r.ate > 0.4
    assert r.ci_low < r.ate < r.ci_high
    assert CLIP_LOW <= r.propensity_range[0] <= r.propensity_range[1] <= CLIP_HIGH

CLIP_LOW = 0.05
CLIP_HIGH = 0.95


# ---------- OPE ----------

@pytest.mark.asyncio
async def test_ope_returns_estimates_for_matching_policy():
    # Seed bandit arms + recoveries so OPE has data + propensities
    async with SessionLocal() as s:
        s.add(BanditArm(cohort="bank_downtime", ticket_bucket="small",
                        hour_bucket="day", action="retry",
                        alpha=8, beta=2, pulls=10))
        s.add(BanditArm(cohort="bank_downtime", ticket_bucket="small",
                        hour_bucket="day", action="payment_link_dunning",
                        alpha=3, beta=7, pulls=10))
        await s.commit()
    for i in range(20):
        await _seed("agent", "bank_downtime", 30_000, i < 16, action="retry")
    async with SessionLocal() as s:
        r = await ope.evaluate(s, target_policy={"bank_downtime": "retry"})
    assert r is not None
    assert r.n >= 15
    assert r.n_matched >= 15
    assert 0 <= r.v_dm <= 1 and 0 <= r.v_dr <= 1


# ---------- Conformal ----------

@pytest.mark.asyncio
async def test_conformal_calibrates_and_returns_interval():
    # Train uplift on enough data
    for i in range(40):
        await _seed("agent", "network_timeout", 30_000, i < 30)
        await _seed("naive", "network_timeout", 30_000, i < 4)
    async with SessionLocal() as s:
        m = await uplift.train(s, min_per_arm=30)
    assert m is not None
    async with SessionLocal() as s:
        cal = await conformal.calibrate(s, alpha=0.05)
    assert cal is not None
    assert cal.quantile >= 0
    p = uplift.predict(cohort="network_timeout", amount_paise=30_000)
    out = conformal.apply_to_prediction(p.p_agent, p.p_naive, p.ite)
    assert out["calibrated"] is True
    assert out["ite_lower"] <= out["ite"] <= out["ite_upper"]


# ---------- mSPRT ----------

@pytest.mark.asyncio
async def test_msprt_declares_reject_null_when_effect_is_huge():
    # Big and unambiguous lift
    for i in range(200):
        await _seed("agent", "insufficient_funds", 100, i < 180)  # 90%
        await _seed("naive", "insufficient_funds", 100, i < 20)   # 10%
    async with SessionLocal() as s:
        r = await sequential.evaluate(s, alpha=0.05, tau=0.05)
    assert r is not None
    assert r.decision == "reject_null"
    assert r.stopped is True
    assert r.delta_hat > 0.5


@pytest.mark.asyncio
async def test_msprt_continues_when_effect_is_small_and_underpowered():
    # Tiny effect, few samples → continue
    for i in range(10):
        await _seed("agent", "network_timeout", 100, i < 6)
        await _seed("naive", "network_timeout", 100, i < 5)
    async with SessionLocal() as s:
        r = await sequential.evaluate(s, alpha=0.05, tau=0.05)
    assert r is not None
    assert r.decision == "continue"
    assert r.stopped is False


# ---------- JS drift ----------

@pytest.mark.asyncio
async def test_js_divergence_flags_joint_distribution_shift():
    now = datetime.now(timezone.utc)
    baseline_at = now - timedelta(hours=48)
    recent_at = now - timedelta(minutes=30)
    # Baseline: even mix
    for _ in range(30):
        await _seed("agent", "bank_downtime", 30_000, True, when=baseline_at)
        await _seed("agent", "network_timeout", 30_000, True, when=baseline_at)
    # Recent: skewed
    for _ in range(30):
        await _seed("agent", "insufficient_funds", 600_000, True, when=recent_at)
    async with SessionLocal() as s:
        r = await drift_kl.compute(s, min_recent=20)
    assert r is not None
    assert r.js_divergence > 0.15
    assert r.severity in {"warn", "critical"}


# ---------- Endpoints ----------

@pytest.mark.asyncio
async def test_advanced_endpoints_smoke():
    for i in range(50):
        await _seed("agent", "bank_downtime", 30_000, i < 40)
        await _seed("naive", "bank_downtime", 30_000, i < 10)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        aipw = (await c.get("/api/causal/aipw")).json()
        msprt = (await c.get("/api/sequential/msprt")).json()
    assert aipw["available"] is True
    assert aipw["ate"] > 0
    assert msprt["available"] is True
    assert msprt["decision"] in {"reject_null", "continue", "accept_null"}
