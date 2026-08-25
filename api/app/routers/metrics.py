from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus, get_session
from app.learning import all_learned_rates
from app.reliability import duplicate_counter, rate_limiter, razorpay_circuit

router = APIRouter()


@router.get("/reliability")
async def reliability(session: AsyncSession = Depends(get_session)):
    return {
        "duplicates_dropped_total": duplicate_counter.value(),
        "rate_limiter": rate_limiter.snapshot(),
        "razorpay_circuit": razorpay_circuit.snapshot(),
    }


@router.get("/learned")
async def learned(session: AsyncSession = Depends(get_session)):
    rows = await all_learned_rates(session)
    return {"rows": rows}


@router.get("/drift")
async def drift(
    baseline_hours: int = Query(default=24 * 7, ge=1, le=24 * 90),
    recent_hours: int = Query(default=6, ge=1, le=48),
    min_recent_count: int = Query(default=20, ge=1),
    session: AsyncSession = Depends(get_session),
):
    """Cohort-mix drift alerts — flag cohorts whose share of recent failures
    diverged materially from the baseline. Actionable upstream (e.g. bank
    downtime spiking means the merchant should call their acquirer)."""
    now = datetime.now(timezone.utc)
    baseline_since = now - timedelta(hours=baseline_hours)
    recent_since = now - timedelta(hours=recent_hours)

    def _shares(rows):
        total = sum(int(r[1]) for r in rows) or 1
        return {r[0]: int(r[1]) / total for r in rows}, total

    baseline_rows = (await session.execute(
        select(Recovery.cohort, func.count(Recovery.id))
        .where(Recovery.created_at >= baseline_since,
               Recovery.created_at < recent_since,
               Recovery.strategy_mode == "agent")
        .group_by(Recovery.cohort)
    )).all()
    recent_rows = (await session.execute(
        select(Recovery.cohort, func.count(Recovery.id))
        .where(Recovery.created_at >= recent_since,
               Recovery.strategy_mode == "agent")
        .group_by(Recovery.cohort)
    )).all()

    baseline_share, baseline_total = _shares(baseline_rows)
    recent_share, recent_total = _shares(recent_rows)

    if recent_total < min_recent_count:
        return {"alerts": [], "reason": f"recent window too small ({recent_total} < {min_recent_count})",
                "baseline_total": baseline_total, "recent_total": recent_total}

    alerts = []
    for cohort in set(baseline_share) | set(recent_share):
        b = baseline_share.get(cohort, 0.0)
        r = recent_share.get(cohort, 0.0)
        delta = r - b
        # Threshold: 10 percentage points of drift AND at least 5 events in recent
        recent_count = int(next((c for co, c in recent_rows if co == cohort), 0))
        if abs(delta) < 0.10 or recent_count < 5:
            continue
        severity = "critical" if abs(delta) >= 0.25 else ("warn" if abs(delta) >= 0.15 else "info")
        alerts.append({
            "cohort": cohort,
            "baseline_share": b,
            "recent_share": r,
            "delta_pp": delta,
            "severity": severity,
            "recent_count": recent_count,
        })
    alerts.sort(key=lambda a: abs(a["delta_pp"]), reverse=True)
    return {"alerts": alerts, "baseline_total": baseline_total, "recent_total": recent_total}


async def _mode_summary(session: AsyncSession, since: datetime, mode: str) -> dict:
    where = [Recovery.created_at >= since, Recovery.strategy_mode == mode]

    total_amount = (await session.scalar(
        select(func.coalesce(func.sum(Recovery.amount_paise), 0)).where(*where)
    )) or 0
    recovered_amount = (await session.scalar(
        select(func.coalesce(func.sum(Recovery.recovered_amount_paise), 0)).where(*where)
    )) or 0
    fees_paid = (await session.scalar(
        select(func.coalesce(func.sum(Recovery.gateway_fee_paise), 0)).where(*where)
    )) or 0
    attempts_total = (await session.scalar(
        select(func.coalesce(func.sum(Recovery.attempts), 0)).where(*where)
    )) or 0
    total_count = (await session.scalar(
        select(func.count(Recovery.id)).where(*where)
    )) or 0
    recovered_count = (await session.scalar(
        select(func.count(Recovery.id)).where(*where, Recovery.status == RecoveryStatus.RECOVERED.value)
    )) or 0
    lost_count = (await session.scalar(
        select(func.count(Recovery.id)).where(*where, Recovery.status == RecoveryStatus.LOST.value)
    )) or 0
    skipped_count = (await session.scalar(
        select(func.count(Recovery.id)).where(*where, Recovery.status == RecoveryStatus.SKIPPED.value)
    )) or 0

    attempted = recovered_count + lost_count
    precision = (recovered_count / attempted) if attempted else 0.0
    recovery_rate = (recovered_amount / total_amount) if total_amount else 0.0

    return {
        "mode": mode,
        "total_amount_paise": int(total_amount),
        "recovered_amount_paise": int(recovered_amount),
        "recovery_rate": recovery_rate,
        "precision": precision,
        "gateway_fees_paise": int(fees_paid),
        "attempts_total": int(attempts_total),
        "counts": {
            "total": int(total_count),
            "recovered": int(recovered_count),
            "lost": int(lost_count),
            "skipped": int(skipped_count),
        },
    }


@router.get("/summary")
async def summary(
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    agent = await _mode_summary(session, since, "agent")
    return {"window_hours": hours, **{k: v for k, v in agent.items() if k != "mode"}}


@router.get("/compare")
async def compare(
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    """Agent vs naive baseline over the same window. If naive hasn't been run,
    naive.counts.total will be 0 — kick off /api/simulator/benchmark first."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    agent = await _mode_summary(session, since, "agent")
    naive = await _mode_summary(session, since, "naive")

    lift_paise = agent["recovered_amount_paise"] - naive["recovered_amount_paise"]
    fees_saved_paise = naive["gateway_fees_paise"] - agent["gateway_fees_paise"]
    attempts_saved = naive["attempts_total"] - agent["attempts_total"]

    return {
        "window_hours": hours,
        "agent": agent,
        "naive": naive,
        "lift": {
            "extra_recovered_paise": int(lift_paise),
            "fees_saved_paise": int(fees_saved_paise),
            "attempts_saved": int(attempts_saved),
            "recovery_rate_delta": agent["recovery_rate"] - naive["recovery_rate"],
        },
    }


@router.get("/cohorts")
async def cohorts(
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    mode: str = Query(default="agent", pattern="^(agent|naive)$"),
    session: AsyncSession = Depends(get_session),
):
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (await session.execute(
        select(
            Recovery.cohort,
            func.count(Recovery.id),
            func.sum(Recovery.amount_paise),
            func.sum(Recovery.recovered_amount_paise),
            func.sum(Recovery.gateway_fee_paise),
        )
        .where(Recovery.created_at >= since, Recovery.strategy_mode == mode)
        .group_by(Recovery.cohort)
    )).all()

    result = []
    for cohort, count, amt, rec, fees in rows:
        amt = int(amt or 0)
        rec = int(rec or 0)
        result.append({
            "cohort": cohort,
            "count": int(count),
            "amount_paise": amt,
            "recovered_paise": rec,
            "recovery_rate": (rec / amt) if amt else 0.0,
            "gateway_fees_paise": int(fees or 0),
        })
    result.sort(key=lambda r: r["amount_paise"], reverse=True)
    return {"mode": mode, "cohorts": result}
