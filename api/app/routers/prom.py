"""Prometheus text exposition — /metrics scrape endpoint.

Emits gauges (point-in-time state) and counters (monotonic totals) in the
standard text/plain; version=0.0.4 format so any Prometheus/VictoriaMetrics/
Grafana Agent scrape config works out of the box. No prometheus_client
dependency — payload is small and the format is stable.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery, RecoveryStatus, get_session
from app.reliability import duplicate_counter, rate_limiter, razorpay_circuit

router = APIRouter()


def _line(name: str, help_: str, type_: str, samples: list[tuple[dict, float]]) -> str:
    out = [f"# HELP {name} {help_}", f"# TYPE {name} {type_}"]
    for labels, value in samples:
        if labels:
            l = ",".join(f'{k}="{v}"' for k, v in labels.items())
            out.append(f"{name}{{{l}}} {value}")
        else:
            out.append(f"{name} {value}")
    return "\n".join(out)


@router.get("", response_class=PlainTextResponse)
async def metrics(session: AsyncSession = Depends(get_session)):
    since = datetime.now(timezone.utc) - timedelta(hours=24 * 30)

    # Per (mode, status) recovery counts
    status_rows = (await session.execute(
        select(Recovery.strategy_mode, Recovery.status, func.count(Recovery.id))
        .where(Recovery.created_at >= since)
        .group_by(Recovery.strategy_mode, Recovery.status)
    )).all()
    recovery_counts = [
        ({"mode": mode, "status": status}, int(n))
        for mode, status, n in status_rows
    ]

    # Per-cohort recovered/eligible sums
    cohort_rows = (await session.execute(
        select(
            Recovery.cohort,
            func.coalesce(func.sum(Recovery.amount_paise), 0),
            func.coalesce(func.sum(Recovery.recovered_amount_paise), 0),
            func.coalesce(func.sum(Recovery.gateway_fee_paise), 0),
            func.coalesce(func.sum(Recovery.attempts), 0),
        ).where(Recovery.created_at >= since, Recovery.strategy_mode == "agent")
        .group_by(Recovery.cohort)
    )).all()

    eligible_samples = [({"cohort": c}, int(amt or 0)) for c, amt, _, _, _ in cohort_rows]
    recovered_samples = [({"cohort": c}, int(rec or 0)) for c, _, rec, _, _ in cohort_rows]
    fees_samples = [({"cohort": c}, int(fees or 0)) for c, _, _, fees, _ in cohort_rows]
    attempts_samples = [({"cohort": c}, int(att or 0)) for c, _, _, _, att in cohort_rows]

    # Circuit state as three gauges (mutually exclusive 1/0)
    circuit_state = razorpay_circuit.snapshot()["state"]
    circuit_samples = [
        ({"state": s}, 1 if s == circuit_state else 0)
        for s in ("closed", "open", "half_open")
    ]

    parts = [
        _line("recoup_recoveries_total",
              "Recoveries by mode and terminal status (30d window)",
              "gauge", recovery_counts),
        _line("recoup_eligible_amount_paise",
              "Eligible ₹ (in paise) by cohort — money we could have recovered",
              "gauge", eligible_samples),
        _line("recoup_recovered_amount_paise",
              "Actually recovered ₹ (in paise) by cohort",
              "gauge", recovered_samples),
        _line("recoup_gateway_fees_paise",
              "Cumulative Razorpay gateway fees spent (in paise) by cohort",
              "gauge", fees_samples),
        _line("recoup_attempts_total",
              "Total attempts made by cohort (retries + link creates + nudges)",
              "gauge", attempts_samples),
        _line("recoup_duplicates_dropped_total",
              "Duplicate webhooks rejected since process start",
              "counter", [({}, duplicate_counter.value())]),
        _line("recoup_rate_limit_denials_total",
              "Per-customer rate limit denials since process start",
              "counter", [({}, rate_limiter.snapshot()["denials_total"])]),
        _line("recoup_rate_limit_customers_tracked",
              "Distinct customer_ids currently in the rate limiter window",
              "gauge", [({}, rate_limiter.snapshot()["customers_tracked"])]),
        _line("recoup_razorpay_circuit_state",
              "Razorpay client circuit breaker state (1 = active)",
              "gauge", circuit_samples),
    ]
    return "\n".join(parts) + "\n"
