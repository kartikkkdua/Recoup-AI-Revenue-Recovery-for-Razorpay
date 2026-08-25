"""Subscription-only funnel — MRR retention view.

Filters recoveries that came from subscription events (`razorpay_subscription_id`
is populated). Reports MRR-at-risk, MRR retained, churn count, and the funnel
attempted → link sent → paid.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus, get_session

router = APIRouter()


@router.get("/summary")
async def summary(
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    base = [Recovery.created_at >= since,
            Recovery.strategy_mode == "agent",
            Recovery.razorpay_subscription_id.is_not(None)]

    total = (await session.scalar(select(func.count(Recovery.id)).where(*base))) or 0
    mrr_at_risk = (await session.scalar(select(func.coalesce(
        func.sum(Recovery.amount_paise), 0)).where(*base))) or 0
    mrr_retained = (await session.scalar(select(func.coalesce(
        func.sum(Recovery.recovered_amount_paise), 0)).where(*base))) or 0
    recovered = (await session.scalar(select(func.count(Recovery.id)).where(
        *base, Recovery.status == RecoveryStatus.RECOVERED.value))) or 0
    churned = (await session.scalar(select(func.count(Recovery.id)).where(
        *base, Recovery.status == RecoveryStatus.LOST.value))) or 0
    in_flight = (await session.scalar(select(func.count(Recovery.id)).where(
        *base, Recovery.status == RecoveryStatus.IN_PROGRESS.value))) or 0

    return {
        "window_hours": hours,
        "counts": {"total": int(total), "recovered": int(recovered),
                   "churned": int(churned), "in_flight": int(in_flight)},
        "mrr_at_risk_paise": int(mrr_at_risk),
        "mrr_retained_paise": int(mrr_retained),
        "retention_rate": (int(mrr_retained) / int(mrr_at_risk)) if mrr_at_risk else 0.0,
        # Annualised MRR retained: recovered subscription payments retain the
        # remaining year of billing on average — that's the LTV kicker.
        "annualised_mrr_retained_paise": int(mrr_retained) * 12,
    }


@router.get("")
async def list_subscription_recoveries(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    rows = (await session.scalars(
        select(Recovery)
        .where(Recovery.razorpay_subscription_id.is_not(None),
               Recovery.strategy_mode == "agent")
        .order_by(Recovery.created_at.desc())
        .limit(limit)
    )).all()
    return {
        "items": [
            {
                "id": r.id,
                "subscription_id": r.razorpay_subscription_id,
                "payment_id": r.razorpay_payment_id,
                "amount_paise": r.amount_paise,
                "recovered_paise": r.recovered_amount_paise,
                "cohort": r.cohort,
                "status": r.status,
                "attempts": r.attempts,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }
