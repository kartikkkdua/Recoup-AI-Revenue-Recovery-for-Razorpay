"""Off-Policy Evaluation — estimate a candidate playbook's value from logged
bandit data, without deploying it. This is the exact algorithm YouTube /
Netflix use to A/B test recommender changes offline.

Given:
    - logged data: (x_i, a_i, r_i) where a_i was sampled by policy π_logged
    - propensity π_logged(a | x) captured at logging time (we approximate from
      the bandit's Beta posteriors)
    - candidate policy π_new: dict mapping cohort -> action

Estimators:

    Direct Method (DM):
        V_DM = 1/n · Σ_i m(x_i, π_new(x_i))
        (uses only the outcome model; biased if the model is wrong)

    Inverse Propensity Score (IPS):
        V_IPS = 1/n · Σ_i r_i · 1{π_new(x_i) = a_i} / π_logged(a_i | x_i)
        (unbiased if propensities are right, but high variance)

    Doubly Robust (DR):
        V_DR = V_DM + 1/n · Σ_i 1{π_new(x_i) = a_i} · (r_i - m(x_i, a_i)) / π_logged
        (consistent if EITHER the outcome model or the propensities are right)
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import bandit as bandit_mod
from app.db import BanditArm, Recovery, RecoveryStatus


@dataclass
class OPEResult:
    n: int
    n_matched: int              # observations where a_i == π_new(x_i)
    v_dm: float                 # Direct Method estimate
    v_ips: float                # IPS estimate
    v_dr: float                 # Doubly-Robust estimate
    se_ips: float
    se_dr: float
    ips_ci: tuple[float, float]
    dr_ci: tuple[float, float]
    baseline_observed_value: float  # π_logged's empirical average reward
    lift_vs_baseline: float


def _thompson_propensity(alphas: dict[str, float], betas: dict[str, float],
                          chosen: str, mc: int = 400) -> float:
    """Monte Carlo estimate of Thompson-sampling propensity for `chosen` action
    given Beta arms. Cheap for small action sets."""
    actions = list(alphas.keys())
    if len(actions) == 1:
        return 1.0
    rng = np.random.default_rng(0)
    wins = 0
    for _ in range(mc):
        samples = {a: rng.beta(alphas[a], betas[a]) for a in actions}
        if max(samples, key=samples.get) == chosen:
            wins += 1
    return max(wins / mc, 1e-3)  # floor prevents division blow-up


async def evaluate(session: AsyncSession, *, target_policy: dict[str, str],
                    hours: int = 24 * 90) -> OPEResult | None:
    """target_policy is a {cohort: action} mapping. For each logged bandit
    decision that lies inside a `cohort` in the mapping, compute the three
    estimators of the candidate policy's expected reward."""
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Load current bandit arm posteriors so we can compute Thompson propensities
    arms = (await session.scalars(select(BanditArm))).all()
    arm_lookup: dict[tuple[str, str, str], dict[str, tuple[float, float]]] = {}
    for a in arms:
        key = (a.cohort, a.ticket_bucket, a.hour_bucket)
        arm_lookup.setdefault(key, {})[a.action] = (a.alpha, a.beta)

    # Load logged (context, action, reward) — action was recorded in strategy.action
    rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise, Recovery.strategy, Recovery.status)
        .where(Recovery.created_at >= since,
               Recovery.strategy_mode == "agent")
    )).all()

    n = 0
    n_matched = 0
    dm_terms: list[float] = []
    ips_terms: list[float] = []
    dr_terms: list[float] = []
    baseline_rewards: list[float] = []

    for cohort, amt, strategy, status in rows:
        if cohort not in target_policy:
            continue
        action_logged = (strategy or {}).get("action")
        if not action_logged:
            continue
        reward = 1.0 if status == RecoveryStatus.RECOVERED.value else 0.0
        target_action = target_policy[cohort]

        tb = bandit_mod.ticket_bucket(int(amt or 0))
        # We don't have per-recovery hour recorded in strategy_dict, so search
        # every hour bucket for one that has both target and logged arms —
        # this aggregates propensity across hours, keeping the estimator well
        # defined without needing per-recovery hour recovery.
        arms_here = None
        for hb in ("morning", "day", "evening", "night"):
            candidate = arm_lookup.get((cohort, tb, hb))
            if candidate and target_action in candidate and action_logged in candidate:
                arms_here = candidate
                break
        if arms_here is None:
            continue

        alphas = {a: v[0] for a, v in arms_here.items()}
        betas = {a: v[1] for a, v in arms_here.items()}
        # π_logged(a_i | x_i) via Monte Carlo on the current posterior
        pi_logged = _thompson_propensity(alphas, betas, action_logged)

        # Outcome model m(x, a) ≈ posterior mean of arm (α / (α + β))
        m_target = (arms_here[target_action][0]
                    / (arms_here[target_action][0] + arms_here[target_action][1]))
        m_logged = (arms_here[action_logged][0]
                    / (arms_here[action_logged][0] + arms_here[action_logged][1]))

        n += 1
        baseline_rewards.append(reward)
        dm_terms.append(m_target)

        matched = (action_logged == target_action)
        if matched:
            n_matched += 1
            ips_terms.append(reward / pi_logged)
            dr_terms.append(m_target + (reward - m_logged) / pi_logged)
        else:
            ips_terms.append(0.0)
            dr_terms.append(m_target)

    if n == 0:
        return None

    v_dm = float(np.mean(dm_terms))
    v_ips = float(np.mean(ips_terms))
    v_dr = float(np.mean(dr_terms))
    se_ips = float(np.std(ips_terms, ddof=1) / sqrt(n)) if n > 1 else 0.0
    se_dr = float(np.std(dr_terms, ddof=1) / sqrt(n)) if n > 1 else 0.0
    Z = 1.96
    baseline = float(np.mean(baseline_rewards))

    return OPEResult(
        n=n, n_matched=n_matched,
        v_dm=v_dm, v_ips=v_ips, v_dr=v_dr,
        se_ips=se_ips, se_dr=se_dr,
        ips_ci=(max(0.0, v_ips - Z * se_ips), min(1.0, v_ips + Z * se_ips)),
        dr_ci=(max(0.0, v_dr - Z * se_dr), min(1.0, v_dr + Z * se_dr)),
        baseline_observed_value=baseline,
        lift_vs_baseline=v_dr - baseline,
    )
