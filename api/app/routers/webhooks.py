from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import handle_event
from app.closer import CLOSE_EVENT_TYPES, handle_close_event
from app.config import settings
from app.db import WebhookEvent, get_session
from app.razorpay_signature import verify_webhook_signature
from app.reliability import duplicate_counter

router = APIRouter()

FAILURE_EVENT_TYPES = {
    "payment.failed",
    "subscription.charged.failed",
}


@router.post("")
async def receive(
    request: Request,
    background: BackgroundTasks,
    x_razorpay_signature: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    raw = await request.body()
    if not verify_webhook_signature(raw, x_razorpay_signature or "", settings.razorpay_webhook_secret):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()
    event_id = payload.get("id") or payload.get("event_id")
    event_type = payload.get("event") or "unknown"
    if not event_id:
        raise HTTPException(status_code=400, detail="missing event id")

    existing = await session.scalar(
        select(WebhookEvent).where(WebhookEvent.razorpay_event_id == event_id)
    )
    if existing:
        n = await duplicate_counter.bump()
        return {"status": "duplicate", "event_id": event_id, "duplicates_dropped_total": n}

    event = WebhookEvent(razorpay_event_id=event_id, event_type=event_type, payload=payload)
    session.add(event)
    await session.commit()
    await session.refresh(event)

    if event_type in FAILURE_EVENT_TYPES:
        background.add_task(handle_event, event.id)
        route = "agent"
    elif event_type in CLOSE_EVENT_TYPES:
        background.add_task(handle_close_event, event_type, payload)
        route = "closer"
    else:
        route = "stored_only"

    return {"status": "accepted", "event_id": event_id, "route": route}
