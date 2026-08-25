"""ROI calculator — projects Recoup's impact for a merchant from their volume.

The cohort mix defaults are calibrated to the same distribution the scenario
generator uses (public Indian fintech benchmarks). The per-cohort agent and
naive recovery rates come from actual observed benchmark runs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus, get_session

router = APIRouter()


# (cohort, mix_share, agent_recovery_rate, naive_recovery_rate)
DEFAULT_MIX = [
    ("insufficient_funds", 0.28, 0.78, 0.011),
    ("bank_downtime",      0.22, 0.75, 0.20),
    ("network_timeout",    0.15, 0.76, 0.60),
    ("auth_expired",       0.10, 0.53, 0.12),
    ("card_declined",      0.10, 0.26, 0.084),
    ("upi_psp_error",      0.08, 0.55, 0.37),
    ("risk_declined",      0.05, 0.00, 0.00),
    ("unknown",            0.02, 0.00, 0.02),
]

# Costs per action (paise) — same numbers the executor charges
FEE_ATTEMPT_PAISE = 200
FEE_LINK_PAISE = 100


class RoiIn(BaseModel):
    monthly_failed_txns: int = Field(..., ge=1, description="Failed payment attempts per month")
    avg_ticket_rupees: float = Field(..., ge=1)
    subscription_share_pct: float = Field(default=0.0, ge=0, le=100,
                                          description="What % of these are subscription charges — subscriptions weight higher because MRR compounds")


@router.get("/defaults")
async def defaults(session: AsyncSession = Depends(get_session)):
    """Return the cohort mix / recovery-rate table. If we have enough observed
    data on this instance, overlay it on top of the seed defaults."""
    observed = {}
    total_agent = await session.scalar(
        select(func.count(Recovery.id)).where(Recovery.strategy_mode == "agent")
    ) or 0
    if total_agent > 100:
        rows = (await session.execute(
            select(
                Recovery.cohort,
                func.count(Recovery.id),
                func.sum(Recovery.amount_paise),
                func.sum(Recovery.recovered_amount_paise),
            ).where(Recovery.strategy_mode == "agent").group_by(Recovery.cohort)
        )).all()
        for cohort, cnt, amt, rec in rows:
            amt = int(amt or 0)
            observed[cohort] = {
                "share": int(cnt) / total_agent,
                "agent_rate": (int(rec or 0) / amt) if amt else 0.0,
            }

    mix = []
    for cohort, default_share, agent_p, naive_p in DEFAULT_MIX:
        o = observed.get(cohort)
        mix.append({
            "cohort": cohort,
            "share": (o["share"] if o else default_share),
            "agent_recovery_rate": (o["agent_rate"] if o else agent_p),
            "naive_recovery_rate": naive_p,
            "sourced_from": "observed" if o else "seed",
        })
    return {"mix": mix, "fees": {"attempt_paise": FEE_ATTEMPT_PAISE, "link_paise": FEE_LINK_PAISE}}


@router.post("/estimate")
async def estimate(body: RoiIn, session: AsyncSession = Depends(get_session)):
    d = await defaults(session)
    mix = d["mix"]
    avg_ticket_paise = int(body.avg_ticket_rupees * 100)
    monthly_eligible_paise = body.monthly_failed_txns * avg_ticket_paise

    agent_weighted = sum(m["share"] * m["agent_recovery_rate"] for m in mix)
    naive_weighted = sum(m["share"] * m["naive_recovery_rate"] for m in mix)

    # Monthly recovered is a fraction of monthly eligible — never more.
    agent_monthly_recovered = int(monthly_eligible_paise * agent_weighted)
    naive_monthly_recovered = int(monthly_eligible_paise * naive_weighted)
    lift_monthly = agent_monthly_recovered - naive_monthly_recovered

    # Subscription LTV bonus applies only to the annual/lift-annualised view:
    # a saved subscription payment retains MRR for the rest of the year, so
    # its lifetime value multiplies. Non-subscription revenue does not.
    sub_share = body.subscription_share_pct / 100.0
    sub_ltv_bonus_multiplier = 1.0 + sub_share * 2.0  # extra 2x annual on the subscription slice

    # Fee model: agent averages ~1.5 actions per failure (per benchmark);
    # naive averages ~2.7 attempts per failure (every txn tried 3x, some skipped).
    agent_monthly_fees = int(body.monthly_failed_txns * 1.5 * FEE_ATTEMPT_PAISE)
    naive_monthly_fees = int(body.monthly_failed_txns * 2.7 * FEE_ATTEMPT_PAISE)
    fees_saved_monthly = naive_monthly_fees - agent_monthly_fees

    return {
        "monthly": {
            "eligible_paise": monthly_eligible_paise,
            "agent_recovered_paise": agent_monthly_recovered,
            "naive_recovered_paise": naive_monthly_recovered,
            "lift_paise": lift_monthly,
            "fees_agent_paise": agent_monthly_fees,
            "fees_naive_paise": naive_monthly_fees,
            "fees_saved_paise": fees_saved_monthly,
        },
        "annual": {
            "eligible_paise": monthly_eligible_paise * 12,
            "agent_recovered_paise": int(agent_monthly_recovered * 12 * sub_ltv_bonus_multiplier),
            "lift_paise": int(lift_monthly * 12 * sub_ltv_bonus_multiplier),
            "fees_saved_paise": fees_saved_monthly * 12,
        },
        "rates": {
            "agent_weighted": agent_weighted,
            "naive_weighted": naive_weighted,
            "sub_ltv_bonus_multiplier": sub_ltv_bonus_multiplier,
        },
        "mix_used": mix,
    }
