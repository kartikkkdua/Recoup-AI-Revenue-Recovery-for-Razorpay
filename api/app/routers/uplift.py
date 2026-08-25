"""Uplift endpoints — train the T-learner, predict per-recovery ITE."""
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import uplift
from app.db import get_session

router = APIRouter()


@router.post("/train")
async def train(
    threshold: float = Query(default=0.05, ge=0.0, le=1.0),
    min_per_arm: int = Query(default=30, ge=5),
    session: AsyncSession = Depends(get_session),
):
    m = await uplift.train(session, min_per_arm=min_per_arm, threshold=threshold)
    if m is None:
        raise HTTPException(status_code=409, detail="not enough data in both arms")
    return {"ok": True, **uplift.snapshot()}


@router.get("/status")
async def status():
    snap = uplift.snapshot()
    return {"trained": snap is not None, "model": snap}


@router.get("/predict")
async def predict(
    cohort: str,
    amount_paise: int = Query(..., ge=1),
    hour_ist: int | None = Query(default=None, ge=0, le=23),
):
    if not uplift.is_trained():
        raise HTTPException(status_code=409, detail="model not trained — POST /train first")
    p = uplift.predict(cohort=cohort, amount_paise=amount_paise, hour_ist=hour_ist)
    if p is None:
        raise HTTPException(status_code=400, detail="prediction failed (unknown features?)")
    return asdict(p)
