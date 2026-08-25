"""Adaptive learning — track observed per-cohort per-action per-hour conversion
rates and let the strategist blend them with hardcoded priors. This is what
makes the "AI" in AI Revenue Recovery real: over time the agent shifts its
probability estimates toward what actually worked for THIS merchant's traffic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._upsert import insert as _insert
from app.db import LearnedOutcome


PRIOR_ALPHA = 4  # pseudo-successes (Beta prior — smooths cold start)
PRIOR_BETA = 6   # pseudo-failures  (so p starts near 40% and drifts to observed)


def _ist_hour_now() -> int:
    return (datetime.now(timezone.utc).hour + 5) % 24  # +5 approximation for hour bucket


async def record_outcome(
    session: AsyncSession, *, cohort: str, action: str, success: bool
) -> None:
    hour = _ist_hour_now()
    stmt = _insert(LearnedOutcome).values(
        cohort=cohort,
        action=action,
        hour_ist=hour,
        attempted=1,
        succeeded=1 if success else 0,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["cohort", "action", "hour_ist"],
        set_={
            "attempted": LearnedOutcome.attempted + 1,
            "succeeded": LearnedOutcome.succeeded + (1 if success else 0),
        },
    )
    await session.execute(stmt)


async def learned_p(
    session: AsyncSession, *, cohort: str, action: str, prior: float
) -> tuple[float, int, float]:
    """Returns (blended_p, observed_attempts, raw_observed_p). Uses a Beta(α,β)
    prior so cold cohorts don't swing wildly on the first few samples."""
    hour = _ist_hour_now()
    row = await session.scalar(
        select(LearnedOutcome).where(
            LearnedOutcome.cohort == cohort,
            LearnedOutcome.action == action,
            LearnedOutcome.hour_ist == hour,
        )
    )
    if not row or row.attempted == 0:
        return prior, 0, 0.0
    raw = row.succeeded / row.attempted
    # Blend: (α + successes) / (α + β + attempts). Prior nudges toward hardcoded p.
    prior_successes = prior * (PRIOR_ALPHA + PRIOR_BETA)
    prior_failures = (PRIOR_ALPHA + PRIOR_BETA) - prior_successes
    blended = (prior_successes + row.succeeded) / (
        prior_successes + prior_failures + row.attempted
    )
    return blended, row.attempted, raw


async def all_learned_rates(session: AsyncSession) -> list[dict]:
    rows = (await session.scalars(select(LearnedOutcome))).all()
    out = []
    for r in rows:
        out.append({
            "cohort": r.cohort,
            "action": r.action,
            "hour_ist": r.hour_ist,
            "attempted": r.attempted,
            "succeeded": r.succeeded,
            "observed_p": (r.succeeded / r.attempted) if r.attempted else 0.0,
        })
    return out
