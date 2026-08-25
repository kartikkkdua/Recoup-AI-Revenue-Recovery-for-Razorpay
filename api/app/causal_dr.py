"""Doubly-Robust ATE via Augmented Inverse Propensity Weighting (AIPW).

CMH stratification (in app/causal.py) is consistent only if the strata capture
all treatment-outcome confounders. AIPW is consistent if EITHER the propensity
model OR the outcome model is right — that's the "doubly robust" property.

Estimator:
    τ_hat = 1/n · Σ_i [ m1(X_i) - m0(X_i)
                       + T_i * (Y_i - m1(X_i)) / e(X_i)
                       - (1-T_i) * (Y_i - m0(X_i)) / (1 - e(X_i)) ]

where:
    e(X) = P(T=1 | X)          — propensity score (LogisticRegression)
    m1(X) = E[Y | X, T=1]      — outcome under treatment (GBM)
    m0(X) = E[Y | X, T=0]      — outcome under control  (GBM)

Standard error from the influence function; 95% CI = τ ± 1.96 · SE / √n.

Propensity is clipped to [0.05, 0.95] to prevent variance blow-up when the
overlap is thin — standard practice.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sqrt

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus

Z95 = 1.96
CLIP = (0.05, 0.95)  # propensity trimming


@dataclass
class AIPWResult:
    n: int
    ate: float
    se: float
    ci_low: float
    ci_high: float
    propensity_mean: float          # sanity check — how balanced is the data
    propensity_range: tuple[float, float]
    outcome_model_auc_agent: float  # holdout-free in-sample AUC as smoke test
    outcome_model_auc_naive: float


def _featurize(cohort: str, amount_paise: int) -> dict:
    if amount_paise < 50_000:  tb = "small"
    elif amount_paise < 500_000: tb = "mid"
    else: tb = "large"
    return {"cohort": cohort, "ticket_bucket": tb,
            "amount_paise": amount_paise,
            "log_amount": np.log1p(amount_paise)}


async def estimate_aipw(session: AsyncSession, *,
                        hours: int = 24 * 90,
                        min_per_arm: int = 30) -> AIPWResult | None:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise, Recovery.strategy_mode, Recovery.status)
        .where(Recovery.created_at >= since,
               Recovery.strategy_mode.in_(("agent", "naive")))
    )).all()
    if not rows:
        return None

    feats: list[dict] = []
    y: list[int] = []
    t: list[int] = []
    for cohort, amt, mode, status in rows:
        feats.append(_featurize(cohort, int(amt or 0)))
        y.append(1 if status == RecoveryStatus.RECOVERED.value else 0)
        t.append(1 if mode == "agent" else 0)

    y = np.asarray(y); t = np.asarray(t)
    if int(t.sum()) < min_per_arm or int((1 - t).sum()) < min_per_arm:
        return None

    cat = np.array([[f["cohort"], f["ticket_bucket"]] for f in feats], dtype=object)
    num = np.array([[f["log_amount"]] for f in feats], dtype=float)
    enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(cat)
    X = np.hstack([enc.transform(cat), num])

    # Propensity e(x) — clipped to prevent tiny denominators
    prop = LogisticRegression(max_iter=1000).fit(X, t)
    e_x = np.clip(prop.predict_proba(X)[:, 1], *CLIP)

    # Outcome models m1(x), m0(x). Fit on each arm separately.
    m1 = GradientBoostingClassifier(max_depth=3, n_estimators=80, random_state=0).fit(X[t == 1], y[t == 1])
    m0 = GradientBoostingClassifier(max_depth=3, n_estimators=80, random_state=0).fit(X[t == 0], y[t == 0])
    m1_x = m1.predict_proba(X)[:, 1]
    m0_x = m0.predict_proba(X)[:, 1]

    # Influence function
    psi = (m1_x - m0_x
           + t * (y - m1_x) / e_x
           - (1 - t) * (y - m0_x) / (1 - e_x))
    ate = float(psi.mean())
    se = float(psi.std(ddof=1) / sqrt(len(psi)))

    # In-sample AUC smoke checks (real practice: cross-fitting; deferred for hackathon scope)
    from sklearn.metrics import roc_auc_score
    try: auc_a = float(roc_auc_score(y[t == 1], m1_x[t == 1]))
    except Exception: auc_a = float("nan")
    try: auc_n = float(roc_auc_score(y[t == 0], m0_x[t == 0]))
    except Exception: auc_n = float("nan")

    return AIPWResult(
        n=len(psi), ate=ate, se=se,
        ci_low=max(-1.0, ate - Z95 * se), ci_high=min(1.0, ate + Z95 * se),
        propensity_mean=float(e_x.mean()),
        propensity_range=(float(e_x.min()), float(e_x.max())),
        outcome_model_auc_agent=auc_a, outcome_model_auc_naive=auc_n,
    )
