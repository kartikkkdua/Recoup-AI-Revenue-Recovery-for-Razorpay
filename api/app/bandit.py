"""Contextual Thompson-sampling bandit for strategy selection.

Context = (cohort, ticket_bucket, hour_bucket).
Arms    = candidate actions valid for that cohort.
Posterior per arm = Beta(alpha, beta), updated on every observed outcome.

Decision: sample p_a ~ Beta(alpha_a, beta_a) for each arm, pick argmax(p_a).
This achieves logarithmic regret (Thompson sampling is asymptotically optimal
for stochastic bandits, and the contextual extension segments the posterior
by (cohort, ticket, hour) so different contexts learn independently).

Cold-start priors are seeded from `AGENT_LINK_P` / `AGENT_RETRY_P` (the
hardcoded rates we used before) so a fresh merchant behaves sensibly and then
drifts to observed reality — exactly the "learn but don't be reckless at t=0"
property that makes bandits practical for money decisions.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._upsert import insert as _insert

from app.db import BanditArm, FailureCohort


# Candidate actions per cohort — matches strategist.py's playbook space.
CANDIDATES: dict[str, list[str]] = {
    FailureCohort.INSUFFICIENT_FUNDS.value: ["payday_retry", "payment_link_dunning"],
    FailureCohort.BANK_DOWNTIME.value: ["retry", "payment_link_dunning"],
    FailureCohort.AUTH_EXPIRED.value: ["tokenization_link", "payment_link_dunning"],
    FailureCohort.NETWORK_TIMEOUT.value: ["retry"],
    FailureCohort.CARD_DECLINED.value: ["rail_switch_link", "payment_link_dunning"],
    FailureCohort.UPI_PSP_ERROR.value: ["retry", "rail_switch_link"],
    FailureCohort.RISK_DECLINED.value: ["human_review"],
    FailureCohort.UNKNOWN.value: ["human_review"],
}

# Prior (alpha, beta) per (cohort, action). Derived from AGENT_*_P priors.
# alpha=4, beta=6 (mean 0.4) or similar — Beta(4,6) is our lightly informative
# smoothing prior; α+β ~= 10 means ~10 pseudo-observations, so real data
# outweighs the prior once we have >10 outcomes for that context.
PRIOR_TABLE: dict[tuple[str, str], tuple[float, float]] = {
    ("insufficient_funds", "payday_retry"):        (4.2, 5.8),  # ~0.42
    ("insufficient_funds", "payment_link_dunning"):(3.5, 6.5),  # ~0.35
    ("bank_downtime", "retry"):                    (5.0, 5.0),  # ~0.50 across attempts
    ("bank_downtime", "payment_link_dunning"):     (2.0, 8.0),  # ~0.20
    ("auth_expired", "tokenization_link"):         (5.8, 4.2),  # ~0.58
    ("auth_expired", "payment_link_dunning"):      (3.0, 7.0),  # ~0.30
    ("network_timeout", "retry"):                  (6.5, 3.5),  # ~0.65
    ("card_declined", "rail_switch_link"):         (2.8, 7.2),  # ~0.28
    ("card_declined", "payment_link_dunning"):     (2.0, 8.0),  # ~0.20
    ("upi_psp_error", "retry"):                    (4.5, 5.5),  # ~0.45
    ("upi_psp_error", "rail_switch_link"):         (3.0, 7.0),  # ~0.30
}


def ticket_bucket(amount_paise: int) -> str:
    if amount_paise < 50_000:      return "small"     # < ₹500
    if amount_paise < 500_000:     return "mid"       # ₹500–5000
    return "large"                                    # ≥ ₹5000


def hour_bucket_ist(hour_ist: int) -> str:
    if 6 <= hour_ist < 12:  return "morning"
    if 12 <= hour_ist < 18: return "day"
    if 18 <= hour_ist < 23: return "evening"
    return "night"


@dataclass
class BanditDecision:
    action: str
    sampled_p: float
    arm_alpha: float
    arm_beta: float
    arm_pulls: int
    context: dict
    considered: list[dict]  # every arm the bandit ranked


async def _get_or_seed(session: AsyncSession, *, cohort: str, ticket: str,
                       hour: str, action: str) -> BanditArm:
    arm = await session.scalar(select(BanditArm).where(
        BanditArm.cohort == cohort, BanditArm.ticket_bucket == ticket,
        BanditArm.hour_bucket == hour, BanditArm.action == action,
    ))
    if arm:
        return arm
    a, b = PRIOR_TABLE.get((cohort, action), (1.0, 1.0))
    arm = BanditArm(cohort=cohort, ticket_bucket=ticket, hour_bucket=hour,
                    action=action, alpha=a, beta=b, pulls=0)
    session.add(arm)
    await session.flush()
    return arm


async def choose(session: AsyncSession, *, cohort: str, amount_paise: int,
                 hour_ist: int, rng: np.random.Generator | None = None) -> BanditDecision:
    rng = rng or np.random.default_rng()
    candidates = CANDIDATES.get(cohort, ["human_review"])
    ticket = ticket_bucket(amount_paise)
    hour = hour_bucket_ist(hour_ist)

    arms = [await _get_or_seed(session, cohort=cohort, ticket=ticket, hour=hour, action=a)
            for a in candidates]

    considered = []
    best_p, best_arm = -1.0, arms[0]
    for arm in arms:
        p = float(rng.beta(arm.alpha, arm.beta))
        considered.append({
            "action": arm.action, "sampled_p": p,
            "alpha": arm.alpha, "beta": arm.beta, "pulls": arm.pulls,
            "posterior_mean": arm.alpha / (arm.alpha + arm.beta),
        })
        if p > best_p:
            best_p, best_arm = p, arm

    return BanditDecision(
        action=best_arm.action,
        sampled_p=best_p,
        arm_alpha=best_arm.alpha,
        arm_beta=best_arm.beta,
        arm_pulls=best_arm.pulls,
        context={"cohort": cohort, "ticket_bucket": ticket, "hour_bucket": hour},
        considered=considered,
    )


async def update(session: AsyncSession, *, cohort: str, amount_paise: int,
                 hour_ist: int, action: str, success: bool) -> None:
    ticket = ticket_bucket(amount_paise)
    hour = hour_bucket_ist(hour_ist)
    a, b = PRIOR_TABLE.get((cohort, action), (1.0, 1.0))

    stmt = _insert(BanditArm).values(
        cohort=cohort, ticket_bucket=ticket, hour_bucket=hour, action=action,
        alpha=a + (1.0 if success else 0.0),
        beta=b + (0.0 if success else 1.0),
        pulls=1,
    ).on_conflict_do_update(
        index_elements=["cohort", "ticket_bucket", "hour_bucket", "action"],
        set_={
            "alpha": BanditArm.alpha + (1.0 if success else 0.0),
            "beta": BanditArm.beta + (0.0 if success else 1.0),
            "pulls": BanditArm.pulls + 1,
        },
    )
    await session.execute(stmt)


async def snapshot(session: AsyncSession) -> list[dict]:
    rows = (await session.scalars(select(BanditArm))).all()
    return [
        {
            "cohort": r.cohort, "ticket_bucket": r.ticket_bucket,
            "hour_bucket": r.hour_bucket, "action": r.action,
            "alpha": r.alpha, "beta": r.beta, "pulls": r.pulls,
            "posterior_mean": r.alpha / (r.alpha + r.beta),
        }
        for r in rows
    ]
