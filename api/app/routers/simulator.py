"""Simulator endpoints — inject synthetic failed-payment events into the pipeline.

Bypasses signature verification (guarded to non-live mode). Supports two modes:
- agent (default): our full classifier + strategist playbook
- naive: retry every failure 3x on the same rail — the industry baseline

Run both back-to-back to produce the agent-vs-naive comparison the dashboard
surfaces on /api/metrics/compare.
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import handle_event
from app.config import settings
from app.db import WebhookEvent, get_session
from simulator.scenarios import generate_batch


class RunRequest(BaseModel):
    count: int = Field(default=100, ge=1, le=2000)
    # SQLite single-writer means high async concurrency thrashes on the write
    # lock. Empirically 8 tops out at ~45-50 events/sec on WAL; higher values
    # (32-64) collapse to ~5/sec under busy_timeout retries.
    concurrency: int = Field(default=8, ge=1, le=200)
    mode: str = Field(default="agent", pattern="^(agent|naive)$")


router = APIRouter()


async def _worker(sem: asyncio.Semaphore, row_id: int, mode: str) -> None:
    async with sem:
        try:
            await handle_event(row_id, mode=mode)
        except Exception:
            pass


@router.post("/run")
async def run(body: RunRequest, session: AsyncSession = Depends(get_session)):
    if settings.razorpay_key_id.startswith("rzp_live_"):
        raise HTTPException(status_code=403, detail="simulator disabled in live mode")

    scenarios = generate_batch(body.count)
    injected: list[int] = []
    for s in scenarios:
        event = WebhookEvent(
            razorpay_event_id=s.payload["id"],
            event_type=s.payload["event"],
            payload=s.payload,
        )
        session.add(event)
        await session.flush()
        injected.append(event.id)
    await session.commit()

    sem = asyncio.Semaphore(body.concurrency)
    for row_id in injected:
        asyncio.create_task(_worker(sem, row_id, body.mode))

    return {"injected": len(injected), "concurrency": body.concurrency, "mode": body.mode}


@router.post("/benchmark")
async def benchmark(
    body: RunRequest,
    session: AsyncSession = Depends(get_session),
):
    """Runs the SAME scenarios through both agent and naive strategies so the
    comparison is apples-to-apples (same distribution, same amounts)."""
    if settings.razorpay_key_id.startswith("rzp_live_"):
        raise HTTPException(status_code=403, detail="simulator disabled in live mode")

    scenarios = generate_batch(body.count)
    agent_ids: list[int] = []
    naive_ids: list[int] = []
    for s in scenarios:
        for mode_ids in (agent_ids, naive_ids):
            e = WebhookEvent(
                razorpay_event_id=s.payload["id"] + ("_a" if mode_ids is agent_ids else "_n"),
                event_type=s.payload["event"],
                payload=s.payload,
            )
            session.add(e)
            await session.flush()
            mode_ids.append(e.id)
    await session.commit()

    sem = asyncio.Semaphore(body.concurrency)
    for rid in agent_ids:
        asyncio.create_task(_worker(sem, rid, "agent"))
    for rid in naive_ids:
        asyncio.create_task(_worker(sem, rid, "naive"))

    return {
        "injected_per_mode": len(agent_ids),
        "total_injected": len(agent_ids) + len(naive_ids),
        "concurrency": body.concurrency,
    }
