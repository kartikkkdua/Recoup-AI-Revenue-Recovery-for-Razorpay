"""Feature store — real-time signals the bandit consumes.

At decision time we look up features about the customer + the merchant's
recent history, cache them on the recovery row (`_features` under strategy),
and pass them to the bandit context and to DecisionExplain on the UI.

Kept SQL-backed and read-only per event so it works with the existing SQLite
setup. At Redis-scale the same interface fronts a Feast/Tecton feature view.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus


@dataclass
class FeatureVec:
    customer_ltv_paise: int          # sum of recovered ₹ for this customer historically
    customer_failure_streak: int     # consecutive failed recoveries for this customer in 24h
    customer_preferred_rail: str | None  # most recovered rail hint for this customer
    cohort_recent_recovery_rate: float   # 24h moving recovery rate for this cohort (agent mode)
    hour_ist: int
    ticket_bucket: str
    is_high_value: bool              # ticket ≥ ₹5000 flag

    def to_dict(self) -> dict:
        return asdict(self)


def _hour_ist_now() -> int:
    return (datetime.now(timezone.utc).hour + 5) % 24


def _ticket_bucket(paise: int) -> str:
    if paise < 50_000:  return "small"
    if paise < 500_000: return "mid"
    return "large"


async def compute_features(
    session: AsyncSession,
    *,
    customer_id: str | None,
    cohort: str,
    amount_paise: int,
) -> FeatureVec:
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    # LTV — all-time recovered ₹ for this customer
    ltv = 0
    streak = 0
    preferred = None
    if customer_id:
        ltv = (await session.scalar(select(func.coalesce(
            func.sum(Recovery.recovered_amount_paise), 0)).where(
            Recovery.merchant_customer_id == customer_id,
            Recovery.status == RecoveryStatus.RECOVERED.value))) or 0

        # Consecutive failures in the last 24h (LOST or SKIPPED count as failed)
        recent_rows = (await session.execute(
            select(Recovery.status).where(
                Recovery.merchant_customer_id == customer_id,
                Recovery.created_at >= since_24h,
            ).order_by(Recovery.created_at.desc())
        )).all()
        for (st,) in recent_rows:
            if st == RecoveryStatus.RECOVERED.value:
                break
            streak += 1

        # Preferred rail: most common rail_hint on this customer's recovered rows
        rail_rows = (await session.execute(
            select(Recovery.strategy).where(
                Recovery.merchant_customer_id == customer_id,
                Recovery.status == RecoveryStatus.RECOVERED.value,
            ).order_by(Recovery.created_at.desc()).limit(20)
        )).all()
        rail_counts: dict[str, int] = {}
        for (strat,) in rail_rows:
            rails = ((strat or {}).get("rails") or [None])
            if rails and rails[0]:
                rail_counts[rails[0]] = rail_counts.get(rails[0], 0) + 1
        preferred = max(rail_counts, key=rail_counts.get) if rail_counts else None

    # Cohort 24h recovery rate (agent mode)
    cohort_totals = await session.execute(
        select(
            func.coalesce(func.sum(Recovery.amount_paise), 0),
            func.coalesce(func.sum(Recovery.recovered_amount_paise), 0),
        ).where(
            Recovery.cohort == cohort,
            Recovery.strategy_mode == "agent",
            Recovery.created_at >= since_24h,
        )
    )
    a, r = cohort_totals.first() or (0, 0)
    a, r = int(a or 0), int(r or 0)
    cohort_rate = (r / a) if a else 0.0

    return FeatureVec(
        customer_ltv_paise=int(ltv),
        customer_failure_streak=int(streak),
        customer_preferred_rail=preferred,
        cohort_recent_recovery_rate=float(cohort_rate),
        hour_ist=_hour_ist_now(),
        ticket_bucket=_ticket_bucket(amount_paise),
        is_high_value=amount_paise >= 500_000,
    )
