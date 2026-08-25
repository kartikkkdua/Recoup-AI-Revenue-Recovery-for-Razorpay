"""Uplift modelling — T-learner for per-recovery Individual Treatment Effect.

CATE tells us "the agent lifts recovery for slice X by 51pp on average."
Uplift modelling tells us the sharper question: **for THIS specific failure,
right now, given its features — how much lift do we predict?**

Method: T-learner (two-model approach). Fit one sklearn model on agent-arm
data mapping features → P(recovered | agent), and a second on naive-arm data
mapping features → P(recovered | naive). Individual Treatment Effect is the
difference of the two predictions.

Business use: gate the intervention. If ITE < threshold (say +5pp), the agent
predicts it can't actually help this failure — skip and don't burn gateway
fees. That's the money story: "we don't spend on failures we can't recover."

Model is fit lazily from the recoveries table on first use (or when
retrain() is called) and cached in-process. Retrain periodically as data
grows. At production scale swap this for a background training pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import OneHotEncoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus


# Feature order the models expect — categorical are one-hot encoded, numeric are raw.
CATEGORICAL_FEATURES = ["cohort", "ticket_bucket", "hour_bucket"]
NUMERIC_FEATURES = ["is_high_value", "amount_paise"]


@dataclass
class UpliftPrediction:
    p_agent: float
    p_naive: float
    ite: float                     # p_agent - p_naive
    should_intervene: bool         # ite >= threshold
    threshold: float
    model_n_agent: int
    model_n_naive: int


@dataclass
class UpliftModel:
    encoder: OneHotEncoder
    model_agent: GradientBoostingClassifier
    model_naive: GradientBoostingClassifier
    n_agent: int
    n_naive: int
    trained_at: datetime
    threshold: float = 0.05  # skip intervention if predicted ITE < 5pp


# Module-level cache. Threading is fine because sklearn predict is thread-safe
# and we only reassign atomically.
_model: UpliftModel | None = None


def _ticket_bucket(paise: int) -> str:
    if paise < 50_000:  return "small"
    if paise < 500_000: return "mid"
    return "large"


def _hour_bucket_ist_now() -> str:
    h = (datetime.now(timezone.utc).hour + 5) % 24
    if 6 <= h < 12:  return "morning"
    if 12 <= h < 18: return "day"
    if 18 <= h < 23: return "evening"
    return "night"


def _hour_bucket_ist(hour_ist: int) -> str:
    if 6 <= hour_ist < 12:  return "morning"
    if 12 <= hour_ist < 18: return "day"
    if 18 <= hour_ist < 23: return "evening"
    return "night"


def _row_to_features(cohort: str, amount_paise: int, hour_ist: int | None = None) -> dict:
    return {
        "cohort": cohort,
        "ticket_bucket": _ticket_bucket(amount_paise),
        "hour_bucket": _hour_bucket_ist(hour_ist) if hour_ist is not None else _hour_bucket_ist_now(),
        "is_high_value": 1 if amount_paise >= 500_000 else 0,
        "amount_paise": amount_paise,
    }


def _matrix(encoder: OneHotEncoder, feats: list[dict]) -> np.ndarray:
    cat = np.array([[f[c] for c in CATEGORICAL_FEATURES] for f in feats], dtype=object)
    num = np.array([[float(f[c]) for c in NUMERIC_FEATURES] for f in feats], dtype=float)
    cat_x = encoder.transform(cat)
    return np.hstack([cat_x, num])


async def train(session: AsyncSession, *, min_per_arm: int = 30,
                threshold: float = 0.05, window_hours: int = 24 * 90) -> UpliftModel | None:
    """Fit two models from historical recoveries. Returns None if not enough data."""
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise, Recovery.strategy_mode, Recovery.status)
        .where(Recovery.created_at >= since,
               Recovery.strategy_mode.in_(("agent", "naive")))
    )).all()
    agent_x, agent_y, naive_x, naive_y = [], [], [], []
    for cohort, amt, mode, status in rows:
        feats = _row_to_features(cohort, int(amt or 0))
        y = 1 if status == RecoveryStatus.RECOVERED.value else 0
        if mode == "agent":
            agent_x.append(feats); agent_y.append(y)
        else:
            naive_x.append(feats); naive_y.append(y)

    if len(agent_x) < min_per_arm or len(naive_x) < min_per_arm:
        return None

    # Encoder fit on the union — so unseen categories in prediction are handled
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    all_cat = np.array([[f[c] for c in CATEGORICAL_FEATURES] for f in (agent_x + naive_x)], dtype=object)
    encoder.fit(all_cat)

    ma = GradientBoostingClassifier(max_depth=3, n_estimators=80, random_state=0)
    mn = GradientBoostingClassifier(max_depth=3, n_estimators=80, random_state=0)
    ma.fit(_matrix(encoder, agent_x), np.array(agent_y))
    mn.fit(_matrix(encoder, naive_x), np.array(naive_y))

    global _model
    _model = UpliftModel(
        encoder=encoder, model_agent=ma, model_naive=mn,
        n_agent=len(agent_x), n_naive=len(naive_x),
        trained_at=datetime.now(timezone.utc), threshold=threshold,
    )
    return _model


def is_trained() -> bool:
    return _model is not None


def snapshot() -> dict | None:
    if _model is None:
        return None
    return {
        "n_agent": _model.n_agent,
        "n_naive": _model.n_naive,
        "trained_at": _model.trained_at.isoformat(),
        "threshold": _model.threshold,
        "features": {
            "categorical": CATEGORICAL_FEATURES,
            "numeric": NUMERIC_FEATURES,
        },
    }


def predict(*, cohort: str, amount_paise: int, hour_ist: int | None = None) -> UpliftPrediction | None:
    m = _model
    if m is None:
        return None
    feats = [_row_to_features(cohort, amount_paise, hour_ist)]
    try:
        x = _matrix(m.encoder, feats)
    except ValueError:
        return None
    # predict_proba returns [[p_neg, p_pos]] — we want p_pos = P(recovered)
    p_agent = float(m.model_agent.predict_proba(x)[0, 1]) if hasattr(m.model_agent, "predict_proba") else 0.0
    p_naive = float(m.model_naive.predict_proba(x)[0, 1]) if hasattr(m.model_naive, "predict_proba") else 0.0
    ite = p_agent - p_naive
    return UpliftPrediction(
        p_agent=p_agent, p_naive=p_naive, ite=ite,
        should_intervene=(ite >= m.threshold),
        threshold=m.threshold,
        model_n_agent=m.n_agent, model_n_naive=m.n_naive,
    )
