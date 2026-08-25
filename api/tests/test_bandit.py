"""Contextual Thompson-sampling bandit — chooses better arm as data accrues."""
import numpy as np
import pytest

from app import bandit as bandit_mod
from app.db import BanditArm, SessionLocal


@pytest.mark.asyncio
async def test_bucketing_boundaries():
    assert bandit_mod.ticket_bucket(49_999) == "small"
    assert bandit_mod.ticket_bucket(50_000) == "mid"
    assert bandit_mod.ticket_bucket(499_999) == "mid"
    assert bandit_mod.ticket_bucket(500_000) == "large"
    assert bandit_mod.hour_bucket_ist(0) == "night"
    assert bandit_mod.hour_bucket_ist(7) == "morning"
    assert bandit_mod.hour_bucket_ist(14) == "day"
    assert bandit_mod.hour_bucket_ist(20) == "evening"
    assert bandit_mod.hour_bucket_ist(23) == "night"


@pytest.mark.asyncio
async def test_seeds_prior_on_first_choose():
    async with SessionLocal() as s:
        d = await bandit_mod.choose(s, cohort="bank_downtime",
                                    amount_paise=100_000, hour_ist=14,
                                    rng=np.random.default_rng(42))
        await s.commit()
        assert d.action in {"retry", "payment_link_dunning"}
        assert len(d.considered) == 2
        # Prior seeded: pulls=0 initially
        arms = (await s.scalars(bandit_mod.select(BanditArm))).all() if False else \
               [c for c in d.considered]
        for c in d.considered:
            assert c["alpha"] > 0 and c["beta"] > 0


@pytest.mark.asyncio
async def test_update_shifts_posterior_toward_reality():
    rng = np.random.default_rng(0)
    ctx = dict(cohort="upi_psp_error", amount_paise=200_000, hour_ist=15)
    async with SessionLocal() as s:
        # Feed 50 wins for "retry" and 50 losses for "rail_switch_link"
        for _ in range(50):
            await bandit_mod.update(s, **ctx, action="retry", success=True)
            await bandit_mod.update(s, **ctx, action="rail_switch_link", success=False)
        await s.commit()
        # Sample 200 decisions; "retry" should win the vast majority
        counts = {"retry": 0, "rail_switch_link": 0}
        for _ in range(200):
            d = await bandit_mod.choose(s, rng=rng, **ctx)
            counts[d.action] = counts.get(d.action, 0) + 1
        assert counts["retry"] > counts["rail_switch_link"] * 5, counts


@pytest.mark.asyncio
async def test_snapshot_returns_all_arms():
    ctx = dict(cohort="network_timeout", amount_paise=20_000, hour_ist=10)
    async with SessionLocal() as s:
        await bandit_mod.update(s, **ctx, action="retry", success=True)
        await s.commit()
        snap = await bandit_mod.snapshot(s)
    assert any(a["cohort"] == "network_timeout" and a["action"] == "retry"
               and a["pulls"] >= 1 for a in snap)
