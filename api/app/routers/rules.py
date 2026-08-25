from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import FailureCohort, Rule, get_session
from app.strategist import DEFAULT_STRATEGIES, to_dict

router = APIRouter()


class RuleIn(BaseModel):
    cohort: str
    max_attempts: int = Field(default=3, ge=0, le=10)
    backoff_seconds: list[int] = []
    preferred_rails: list[str] = []
    dunning_channels: list[str] = []
    enabled: bool = True


@router.get("")
async def list_rules(session: AsyncSession = Depends(get_session)):
    saved = {r.cohort: r for r in (await session.scalars(select(Rule))).all()}
    items = []
    for cohort in FailureCohort:
        default = DEFAULT_STRATEGIES.get(cohort)
        r = saved.get(cohort.value)
        items.append({
            "cohort": cohort.value,
            "default": to_dict(default) if default else None,
            "override": {
                "max_attempts": r.max_attempts,
                "backoff_seconds": r.backoff_seconds,
                "preferred_rails": r.preferred_rails,
                "dunning_channels": r.dunning_channels,
                "enabled": r.enabled,
            } if r else None,
        })
    return {"items": items}


@router.put("/{cohort}")
async def upsert_rule(cohort: str, body: RuleIn, session: AsyncSession = Depends(get_session)):
    try:
        FailureCohort(cohort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown cohort: {cohort}") from exc

    existing = await session.scalar(select(Rule).where(Rule.cohort == cohort))
    if existing:
        existing.max_attempts = body.max_attempts
        existing.backoff_seconds = body.backoff_seconds
        existing.preferred_rails = body.preferred_rails
        existing.dunning_channels = body.dunning_channels
        existing.enabled = body.enabled
    else:
        session.add(Rule(
            cohort=cohort,
            max_attempts=body.max_attempts,
            backoff_seconds=body.backoff_seconds,
            preferred_rails=body.preferred_rails,
            dunning_channels=body.dunning_channels,
            enabled=body.enabled,
        ))
    await session.commit()
    return {"ok": True}


@router.delete("/{cohort}")
async def reset_rule(cohort: str, session: AsyncSession = Depends(get_session)):
    try:
        FailureCohort(cohort)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"unknown cohort: {cohort}") from exc
    existing = await session.scalar(select(Rule).where(Rule.cohort == cohort))
    if existing:
        await session.delete(existing)
        await session.commit()
    return {"ok": True, "reset": cohort}
