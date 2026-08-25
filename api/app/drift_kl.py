"""Drift detection via Jensen-Shannon divergence.

Share-based drift (in metrics.py) catches marginal shifts in cohort frequency.
JS divergence catches JOINT-distribution shift — a change in the (cohort ×
ticket_bucket) joint that per-cohort share alone misses.

JS is symmetric and bounded in [0, log 2], so it's directly interpretable as
a "how different" score. A JS > 0.10 is a meaningful distribution shift; > 0.25
is major. We also decompose per-cell so a merchant can see which cells drove it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import log

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Recovery


@dataclass
class DriftResult:
    js_divergence: float
    baseline_total: int
    recent_total: int
    max_cell: str
    max_cell_contribution: float
    per_cell: list[dict]
    severity: str  # "info" | "warn" | "critical"


def _ticket_bucket(paise: int) -> str:
    if paise < 50_000:  return "small"
    if paise < 500_000: return "mid"
    return "large"


def _joint_dist(rows) -> dict[tuple[str, str], float]:
    counts: dict[tuple[str, str], int] = {}
    for cohort, amt in rows:
        key = (cohort, _ticket_bucket(int(amt or 0)))
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values()) or 1
    return {k: v / total for k, v in counts.items()}


def _js(P: dict, Q: dict) -> tuple[float, dict]:
    keys = set(P) | set(Q)
    p = {k: P.get(k, 0.0) for k in keys}
    q = {k: Q.get(k, 0.0) for k in keys}
    m = {k: 0.5 * (p[k] + q[k]) for k in keys}
    def kl(a, b):
        s = 0.0
        for k in keys:
            if a[k] > 0 and b[k] > 0:
                s += a[k] * log(a[k] / b[k])
        return s
    js = 0.5 * kl(p, m) + 0.5 * kl(q, m)
    # Per-cell decomposition (contribution to JS)
    per = {}
    for k in keys:
        if m[k] == 0: per[k] = 0.0; continue
        c = 0.0
        if p[k] > 0: c += 0.5 * p[k] * log(p[k] / m[k])
        if q[k] > 0: c += 0.5 * q[k] * log(q[k] / m[k])
        per[k] = c
    return js, per


async def compute(session: AsyncSession, *,
                   baseline_hours: int = 24 * 7,
                   recent_hours: int = 6,
                   min_recent: int = 20) -> DriftResult | None:
    now = datetime.now(timezone.utc)
    baseline_since = now - timedelta(hours=baseline_hours)
    recent_since = now - timedelta(hours=recent_hours)

    baseline_rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise)
        .where(Recovery.created_at >= baseline_since,
               Recovery.created_at < recent_since,
               Recovery.strategy_mode == "agent")
    )).all()
    recent_rows = (await session.execute(
        select(Recovery.cohort, Recovery.amount_paise)
        .where(Recovery.created_at >= recent_since,
               Recovery.strategy_mode == "agent")
    )).all()

    if len(recent_rows) < min_recent:
        return None

    P = _joint_dist(baseline_rows)
    Q = _joint_dist(recent_rows)
    js, per = _js(P, Q)
    top = max(per, key=per.get) if per else ("-", "-")
    top_contrib = per.get(top, 0.0)

    severity = "info"
    if js >= 0.25: severity = "critical"
    elif js >= 0.10: severity = "warn"

    return DriftResult(
        js_divergence=js,
        baseline_total=len(baseline_rows),
        recent_total=len(recent_rows),
        max_cell=f"{top[0]}/{top[1]}" if isinstance(top, tuple) else str(top),
        max_cell_contribution=top_contrib,
        per_cell=[{"cell": f"{k[0]}/{k[1]}", "contribution": v,
                   "baseline_share": P.get(k, 0.0), "recent_share": Q.get(k, 0.0)}
                  for k, v in sorted(per.items(), key=lambda kv: -kv[1])[:12]],
        severity=severity,
    )
