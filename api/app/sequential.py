"""Mixture Sequential Probability Ratio Test (mSPRT).

Standard A/B testing has a fixed n — you commit up front. mSPRT lets you
peek continuously and stop as soon as evidence is decisive, with proper Type-I
error control. This is Optimizely/Statsig's core algorithm.

For a difference-in-proportions A/B, we use the mixture likelihood ratio with
a normal mixture prior on the effect size δ ~ N(0, τ²):

    Λ_n = √(σ²_n / (σ²_n + τ²)) · exp( n · δ̂_n² / (2 · (σ²_n + τ²)) · τ² / σ²_n )

where δ̂_n is the sample mean difference at step n, σ²_n is its variance.

Decision rule:
    Λ_n > 1/α          → reject H0 (agent > naive) — STOP + declare winner
    Λ_n < α            → accept H0 (no material lift) — STOP + declare null
    otherwise          → CONTINUE

The mixture prior variance τ² tunes sensitivity. τ² = 0.05² is a "we're
looking for effects of order 5pp or larger" default; the merchant can pass a
different τ if they only care about big lifts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import exp, sqrt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus


@dataclass
class MSPRTResult:
    n_agent: int
    n_naive: int
    p_agent: float
    p_naive: float
    delta_hat: float                # sample effect
    variance: float                 # var(δ̂_n)
    tau_squared: float              # prior variance
    likelihood_ratio: float
    log_lr: float
    decision: str                   # "reject_null" | "accept_null" | "continue"
    alpha: float
    stopped: bool


async def evaluate(session: AsyncSession, *,
                    alpha: float = 0.05,
                    tau: float = 0.05,
                    hours: int = 24 * 30) -> MSPRTResult | None:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (await session.execute(
        select(Recovery.strategy_mode, Recovery.status)
        .where(Recovery.created_at >= since,
               Recovery.strategy_mode.in_(("agent", "naive")))
    )).all()
    a_n = a_s = n_n = n_s = 0
    for mode, status in rows:
        succ = 1 if status == RecoveryStatus.RECOVERED.value else 0
        if mode == "agent":
            a_n += 1; a_s += succ
        else:
            n_n += 1; n_s += succ
    if a_n == 0 or n_n == 0:
        return None

    p_a = a_s / a_n
    p_n = n_s / n_n
    delta = p_a - p_n
    var = p_a * (1 - p_a) / a_n + p_n * (1 - p_n) / n_n
    if var <= 0:
        return None
    tau2 = tau ** 2

    # mSPRT statistic — from Johari, Pekelis, Walsh "Peeking at A/B tests" (2015).
    # Log form for numeric stability.
    from math import log
    log_lr = 0.5 * log(var / (var + tau2)) + (delta ** 2 * tau2) / (2 * var * (var + tau2))
    # Guard against overflow when running very long
    log_lr = max(min(log_lr, 500.0), -500.0)
    lr = exp(log_lr)

    if lr >= 1.0 / alpha and delta > 0:
        decision = "reject_null"
        stopped = True
    elif lr <= alpha:
        decision = "accept_null"
        stopped = True
    else:
        decision = "continue"
        stopped = False

    return MSPRTResult(
        n_agent=a_n, n_naive=n_n,
        p_agent=p_a, p_naive=p_n,
        delta_hat=delta, variance=var, tau_squared=tau2,
        likelihood_ratio=lr, log_lr=log_lr,
        decision=decision, alpha=alpha, stopped=stopped,
    )
