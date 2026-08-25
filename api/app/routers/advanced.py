"""Endpoints for Tier A + Tier B — AIPW, OPE, mSPRT, JS drift, conformal."""
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app import causal_dr, conformal, drift_kl, ope, sequential
from app.db import get_session

router = APIRouter()


@router.get("/causal/aipw")
async def aipw(hours: int = Query(default=24 * 90, ge=1, le=24 * 365),
                session: AsyncSession = Depends(get_session)):
    r = await causal_dr.estimate_aipw(session, hours=hours)
    if not r:
        return {"available": False, "reason": "not enough data in both arms"}
    return {"available": True, **asdict(r)}


@router.post("/ope/evaluate")
async def ope_evaluate(
    target_policy: dict[str, str] = Body(..., description="mapping {cohort: action}"),
    hours: int = Query(default=24 * 90, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    r = await ope.evaluate(session, target_policy=target_policy, hours=hours)
    if not r:
        raise HTTPException(status_code=409, detail="no matching logged data — train bandit first")
    return asdict(r)


@router.get("/sequential/msprt")
async def msprt(
    alpha: float = Query(default=0.05, ge=0.001, le=0.5),
    tau: float = Query(default=0.05, ge=0.005, le=0.5),
    hours: int = Query(default=24 * 30, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
):
    r = await sequential.evaluate(session, alpha=alpha, tau=tau, hours=hours)
    if not r:
        return {"available": False, "reason": "not enough data in both arms"}
    return {"available": True, **asdict(r)}


@router.get("/drift/js")
async def drift_js(session: AsyncSession = Depends(get_session)):
    r = await drift_kl.compute(session)
    if not r:
        return {"available": False, "reason": "recent window too small"}
    return {"available": True, **asdict(r)}


@router.post("/conformal/calibrate")
async def conformal_calibrate(
    alpha: float = Query(default=0.05, ge=0.001, le=0.5),
    session: AsyncSession = Depends(get_session),
):
    r = await conformal.calibrate(session, alpha=alpha)
    if not r:
        raise HTTPException(status_code=409, detail="uplift model not trained OR too little data")
    return {"ok": True, **(conformal.snapshot() or {})}


@router.get("/conformal/status")
async def conformal_status():
    snap = conformal.snapshot()
    return {"calibrated": snap is not None, "calibration": snap}
