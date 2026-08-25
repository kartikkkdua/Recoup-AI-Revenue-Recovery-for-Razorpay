"""Server-Sent Events stream so the dashboard ticks live during a benchmark.

Polls the summary every 500ms and emits a message when anything changed.
Deliberately not database triggers or a Redis pubsub — this is one process,
one SQLite file. The polling is cheap and works everywhere including
Cloudflare/Vercel edge, which is where we'll deploy.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.db import Recovery, RecoveryStatus, SessionLocal
from app.reliability import duplicate_counter, rate_limiter, razorpay_circuit

router = APIRouter()


async def _snapshot() -> dict:
    since = datetime.now(timezone.utc) - timedelta(hours=24 * 30)
    async with SessionLocal() as s:
        total = (await s.scalar(select(func.count(Recovery.id)).where(
            Recovery.created_at >= since, Recovery.strategy_mode == "agent"))) or 0
        recovered = (await s.scalar(select(func.count(Recovery.id)).where(
            Recovery.created_at >= since, Recovery.strategy_mode == "agent",
            Recovery.status == RecoveryStatus.RECOVERED.value))) or 0
        recovered_paise = (await s.scalar(select(func.coalesce(
            func.sum(Recovery.recovered_amount_paise), 0)).where(
            Recovery.created_at >= since, Recovery.strategy_mode == "agent"))) or 0
        eligible_paise = (await s.scalar(select(func.coalesce(
            func.sum(Recovery.amount_paise), 0)).where(
            Recovery.created_at >= since, Recovery.strategy_mode == "agent"))) or 0
        latest = (await s.scalar(select(func.max(Recovery.id)).where(
            Recovery.strategy_mode == "agent"))) or 0
    return {
        "total": int(total),
        "recovered": int(recovered),
        "recovered_paise": int(recovered_paise),
        "eligible_paise": int(eligible_paise),
        "recovery_rate": (int(recovered_paise) / int(eligible_paise)) if eligible_paise else 0.0,
        "latest_id": int(latest),
        "duplicates_dropped": duplicate_counter.value(),
        "rate_limit_denials": rate_limiter.snapshot()["denials_total"],
        "circuit": razorpay_circuit.snapshot()["state"],
        "at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/live")
async def live(request: Request):
    """SSE endpoint. Emits `event: tick` every 500ms if anything changed,
    plus a keepalive comment every 15s. Client-side: use EventSource."""
    async def gen():
        last: dict | None = None
        last_keepalive = 0
        while True:
            if await request.is_disconnected():
                break
            snap = await _snapshot()
            if snap != last:
                yield f"event: tick\ndata: {json.dumps(snap)}\n\n"
                last = snap
                last_keepalive = 0
            else:
                last_keepalive += 1
                if last_keepalive % 30 == 0:  # ~15s
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"cache-control": "no-store", "x-accel-buffering": "no"})
