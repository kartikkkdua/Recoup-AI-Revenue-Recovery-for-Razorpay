"""Read the in-memory OTel span buffer (spans emitted since process start)."""
from fastapi import APIRouter, Query

from app import tracing

router = APIRouter()


@router.get("/recent")
async def recent(limit: int = Query(default=100, ge=1, le=1000)):
    return {"spans": tracing.recent_spans(limit)}


@router.delete("/clear")
async def clear():
    tracing.clear_spans()
    return {"ok": True}
