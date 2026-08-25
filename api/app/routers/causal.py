"""Causal impact endpoints — ATE (with 95% CI) and per-slice CATE.

The dashboard's ComparisonPanel shows raw agent-vs-naive numbers. This is the
statistically-defensible version: variance-reduced ATE and per-slice CATE
where the 95% CI excludes zero. This is what you show a data scientist.
"""
from dataclasses import asdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import causal
from app.db import get_session

router = APIRouter()


@router.get("/ate")
async def ate(
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    result = await causal.estimate_ate(session, hours=hours)
    if not result:
        return {"available": False, "reason": "no data in window"}
    return {"available": True, **asdict(result)}


@router.get("/cate")
async def cate(
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    min_per_arm: int = Query(default=5, ge=1),
    session: AsyncSession = Depends(get_session),
):
    slices = await causal.estimate_cate_per_slice(
        session, hours=hours, min_per_arm=min_per_arm)
    return {
        "slices": [asdict(s) for s in slices],
        "n_slices": len(slices),
        "n_significant": sum(1 for s in slices if s.significant),
    }
