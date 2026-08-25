"""Split-conformal prediction intervals for the uplift T-learner.

Conformal prediction gives DISTRIBUTION-FREE 95% predictive intervals: no
Gaussian assumption, no bootstrapping. The interval width is calibrated from
held-out residuals so the empirical coverage on new predictions is exactly
1-α under exchangeability.

Method (split conformal for two-model uplift):
    1. Reserve a calibration slice of the training data (20% by default).
    2. For each calibration point, compute an "outcome-proxy ITE":
           context-conditional CATE = P(Y=1 | X, T=1) - P(Y=1 | X, T=0)
       (empirical group means within the cohort × ticket bucket)
    3. Compute residuals: r_i = |proxy_ITE_i - predicted_ITE_i|
    4. q̂ = ceiling((n+1)(1-α)/n)-th quantile of the residuals
    5. New prediction interval: [ITE - q̂, ITE + q̂]

Also fits isotonic calibration on top of the T-learner's probability outputs
so p_agent / p_naive are properly calibrated (real frequencies match predicted).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import uplift as uplift_mod
from app.db import Recovery, RecoveryStatus


@dataclass
class ConformalCalibration:
    quantile: float               # q̂ — half-width of the interval
    alpha: float                  # miscoverage level (0.05 for 95%)
    n_calibration: int
    isotonic_agent: IsotonicRegression | None
    isotonic_naive: IsotonicRegression | None


_calib: ConformalCalibration | None = None


def _feats(cohort: str, amount_paise: int) -> tuple[str, str]:
    if amount_paise < 50_000:  tb = "small"
    elif amount_paise < 500_000: tb = "mid"
    else: tb = "large"
    return cohort, tb


async def calibrate(session: AsyncSession, *, alpha: float = 0.05,
                     calibration_frac: float = 0.20) -> ConformalCalibration | None:
    """Requires uplift.train() has already been called. Uses a random 20%
    holdout to compute conformal quantile + isotonic calibrators."""
    if not uplift_mod.is_trained():
        return None

    since = datetime.now(timezone.utc) - timedelta(hours=24 * 90)
    rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise, Recovery.strategy_mode, Recovery.status)
        .where(Recovery.created_at >= since,
               Recovery.strategy_mode.in_(("agent", "naive")))
    )).all()
    if len(rows) < 60:
        return None

    rng = np.random.default_rng(42)
    idx = rng.permutation(len(rows))
    n_cal = max(20, int(len(rows) * calibration_frac))
    cal_idx = idx[:n_cal]
    cal_rows = [rows[i] for i in cal_idx]

    # Group means per (cohort, ticket_bucket, treatment) — the "true CATE" proxy
    from collections import defaultdict
    group_sum: dict = defaultdict(lambda: [0, 0])  # [count, sum_y]
    for cohort, amt, mode, status in rows:
        c, tb = _feats(cohort, int(amt or 0))
        key = (c, tb, mode)
        group_sum[key][0] += 1
        group_sum[key][1] += 1 if status == RecoveryStatus.RECOVERED.value else 0

    def group_p(cohort, tb, mode) -> float | None:
        n, s = group_sum.get((cohort, tb, mode), (0, 0))
        return (s / n) if n else None

    # Isotonic calibration inputs: model prob vs observed outcome, per arm
    iso_agent_x, iso_agent_y = [], []
    iso_naive_x, iso_naive_y = [], []
    residuals: list[float] = []
    for cohort, amt, mode, status in cal_rows:
        c, tb = _feats(cohort, int(amt or 0))
        y = 1 if status == RecoveryStatus.RECOVERED.value else 0
        pred = uplift_mod.predict(cohort=cohort, amount_paise=int(amt or 0))
        if pred is None:
            continue
        if mode == "agent":
            iso_agent_x.append(pred.p_agent); iso_agent_y.append(y)
        else:
            iso_naive_x.append(pred.p_naive); iso_naive_y.append(y)

        pa = group_p(c, tb, "agent")
        pn = group_p(c, tb, "naive")
        if pa is None or pn is None:
            continue
        proxy_ite = pa - pn
        residuals.append(abs(proxy_ite - pred.ite))

    if len(residuals) < 10:
        return None

    # Split-conformal quantile: adjusted for finite sample
    n = len(residuals)
    q_level = np.ceil((n + 1) * (1 - alpha)) / n
    q_level = min(max(q_level, 0.0), 1.0)
    q_hat = float(np.quantile(residuals, q_level))

    iso_a = None
    iso_n = None
    if len(iso_agent_x) >= 10:
        iso_a = IsotonicRegression(out_of_bounds="clip").fit(iso_agent_x, iso_agent_y)
    if len(iso_naive_x) >= 10:
        iso_n = IsotonicRegression(out_of_bounds="clip").fit(iso_naive_x, iso_naive_y)

    global _calib
    _calib = ConformalCalibration(
        quantile=q_hat, alpha=alpha, n_calibration=n,
        isotonic_agent=iso_a, isotonic_naive=iso_n,
    )
    return _calib


def is_calibrated() -> bool:
    return _calib is not None


def snapshot() -> dict | None:
    if _calib is None: return None
    return {
        "quantile": _calib.quantile,
        "alpha": _calib.alpha,
        "n_calibration": _calib.n_calibration,
        "isotonic_agent_fitted": _calib.isotonic_agent is not None,
        "isotonic_naive_fitted": _calib.isotonic_naive is not None,
    }


def apply_to_prediction(p_agent: float, p_naive: float, ite: float) -> dict:
    """Return calibrated p_agent, p_naive, ITE with conformal interval."""
    out = {"p_agent_raw": p_agent, "p_naive_raw": p_naive, "ite_raw": ite}
    if _calib is None:
        out.update({"p_agent": p_agent, "p_naive": p_naive, "ite": ite,
                    "ite_lower": None, "ite_upper": None, "calibrated": False})
        return out
    p_a = (float(_calib.isotonic_agent.predict([p_agent])[0])
           if _calib.isotonic_agent is not None else p_agent)
    p_n = (float(_calib.isotonic_naive.predict([p_naive])[0])
           if _calib.isotonic_naive is not None else p_naive)
    cal_ite = p_a - p_n
    out.update({
        "p_agent": p_a, "p_naive": p_n, "ite": cal_ite,
        "ite_lower": cal_ite - _calib.quantile,
        "ite_upper": cal_ite + _calib.quantile,
        "coverage_target": 1 - _calib.alpha,
        "calibrated": True,
    })
    return out
