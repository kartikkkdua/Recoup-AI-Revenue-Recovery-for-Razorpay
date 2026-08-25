"""Causal treatment effect estimation.

The agent-vs-naive comparison in metrics.py is a RAW difference of proportions.
That's fine for a headline, but it doesn't answer the causal question a serious
buyer asks: "How much of the lift is because of the agent — vs. selection bias
in which failures got which strategy?"

Because our simulator injects each scenario twice (once for agent, once for
naive) under the same seed-distribution, we DO have identical covariate
distributions across the two arms — so we can estimate:

- ATE (Average Treatment Effect): agent - naive recovery rate, with a
  variance-reduced estimator using cohort × ticket_bucket as pre-treatment
  strata (Cochran-Mantel-Haenszel / stratified difference-in-proportions).
- CATE (Conditional Average Treatment Effect): the same difference computed
  per slice (cohort × ticket_bucket), with 95% CI from the delta-method
  standard error for a difference of two independent binomials.

This is the "we measure the incremental causal impact, not just the raw
outcome delta" story — the same technique Netflix/Airbnb use for experiment
analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sqrt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus

Z95 = 1.96


@dataclass
class SliceCATE:
    cohort: str
    ticket_bucket: str
    n_agent: int
    n_naive: int
    p_agent: float
    p_naive: float
    cate: float           # p_agent - p_naive
    se: float             # standard error of the difference
    ci_low: float
    ci_high: float
    significant: bool     # 95% CI excludes 0


@dataclass
class ATEResult:
    n_agent: int
    n_naive: int
    p_agent: float
    p_naive: float
    ate_raw: float          # naive difference of proportions
    ate_stratified: float   # Cochran-Mantel-Haenszel style
    se_stratified: float
    ci_low: float
    ci_high: float
    lift_multiple: float    # p_agent / p_naive
    slices_used: int


def _ticket_bucket(paise: int) -> str:
    if paise < 50_000:  return "small"
    if paise < 500_000: return "mid"
    return "large"


def _binomial_ci(p: float, n: int) -> tuple[float, float]:
    if n == 0: return (0.0, 0.0)
    se = sqrt(max(p * (1 - p), 0) / n)
    return (max(0.0, p - Z95 * se), min(1.0, p + Z95 * se))


async def _fetch(session: AsyncSession, since: datetime) -> list[tuple]:
    rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise, Recovery.strategy_mode, Recovery.status)
        .where(Recovery.created_at >= since,
               Recovery.strategy_mode.in_(("agent", "naive")))
    )).all()
    return list(rows)


async def estimate_ate(session: AsyncSession, *, hours: int = 24 * 30,
                       min_per_slice: int = 5) -> ATEResult | None:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await _fetch(session, since)
    if not rows:
        return None

    # Raw
    a_n = a_s = n_n = n_s = 0
    # Stratified: per (cohort, ticket_bucket)
    strata: dict[tuple[str, str], dict[str, list[int]]] = {}
    for cohort, amt, mode, status in rows:
        succ = 1 if status == RecoveryStatus.RECOVERED.value else 0
        if mode == "agent":
            a_n += 1; a_s += succ
        else:
            n_n += 1; n_s += succ
        key = (cohort, _ticket_bucket(int(amt or 0)))
        stratum = strata.setdefault(key, {"a": [0, 0], "n": [0, 0]})  # [n, s]
        stratum[mode[0]][0] += 1
        stratum[mode[0]][1] += succ

    p_agent = a_s / a_n if a_n else 0.0
    p_naive = n_s / n_n if n_n else 0.0
    ate_raw = p_agent - p_naive

    # Stratified estimate: weight each slice by its harmonic-mean sample size
    # (Mantel-Haenszel-style for difference of proportions).
    num = 0.0
    denom = 0.0
    var_sum = 0.0
    slices_used = 0
    for key, s in strata.items():
        na, sa = s["a"]
        nn, sn = s["n"]
        if na < min_per_slice or nn < min_per_slice:
            continue
        pa = sa / na
        pn = sn / nn
        w = (na * nn) / (na + nn)  # harmonic mean weight
        num += w * (pa - pn)
        denom += w
        # Delta-method variance of the difference contribution
        var_sum += (w ** 2) * (pa * (1 - pa) / na + pn * (1 - pn) / nn)
        slices_used += 1

    if denom == 0:
        # Fall back to raw ATE
        ate_strat = ate_raw
        se_strat = sqrt(p_agent*(1-p_agent)/max(a_n,1) + p_naive*(1-p_naive)/max(n_n,1))
    else:
        ate_strat = num / denom
        se_strat = sqrt(var_sum) / denom

    return ATEResult(
        n_agent=a_n, n_naive=n_n,
        p_agent=p_agent, p_naive=p_naive,
        ate_raw=ate_raw,
        ate_stratified=ate_strat,
        se_stratified=se_strat,
        ci_low=max(-1.0, ate_strat - Z95 * se_strat),
        ci_high=min(1.0, ate_strat + Z95 * se_strat),
        lift_multiple=(p_agent / p_naive) if p_naive > 0 else float("inf"),
        slices_used=slices_used,
    )


async def estimate_cate_per_slice(
    session: AsyncSession, *, hours: int = 24 * 30, min_per_arm: int = 5,
) -> list[SliceCATE]:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await _fetch(session, since)
    strata: dict[tuple[str, str], dict[str, list[int]]] = {}
    for cohort, amt, mode, status in rows:
        key = (cohort, _ticket_bucket(int(amt or 0)))
        s = strata.setdefault(key, {"agent": [0, 0], "naive": [0, 0]})
        s[mode][0] += 1
        s[mode][1] += (1 if status == RecoveryStatus.RECOVERED.value else 0)

    out: list[SliceCATE] = []
    for (cohort, tb), s in strata.items():
        na, sa = s["agent"]
        nn, sn = s["naive"]
        if na < min_per_arm or nn < min_per_arm:
            continue
        pa = sa / na
        pn = sn / nn
        cate = pa - pn
        se = sqrt(pa*(1-pa)/na + pn*(1-pn)/nn)
        ci_low = max(-1.0, cate - Z95 * se)
        ci_high = min(1.0, cate + Z95 * se)
        out.append(SliceCATE(
            cohort=cohort, ticket_bucket=tb,
            n_agent=na, n_naive=nn,
            p_agent=pa, p_naive=pn,
            cate=cate, se=se,
            ci_low=ci_low, ci_high=ci_high,
            significant=(ci_low > 0) or (ci_high < 0),
        ))
    out.sort(key=lambda x: x.cate, reverse=True)
    return out
