"""Close-loop handlers for success/terminal Razorpay events.

Failure webhooks (payment.failed, subscription.charged.failed) are routed to
the agent. The events below indicate that a recovery attempt actually landed
(or was ended by another path) and update the corresponding Recovery row.

- payment_link.paid   → payment link we sent was clicked and paid; recovery succeeded
- payment.captured    → a retry order we created was captured; recovery succeeded
- subscription.halted / subscription.completed → close any still-open recovery for that subscription
- refund.processed    → the "recovered" payment was refunded; retract the recovery
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AuditEntry, Recovery, RecoveryStatus, SessionLocal


def _audit(session: AsyncSession, recovery_id: int, step: str, actor: str, detail: dict) -> None:
    session.add(AuditEntry(recovery_id=recovery_id, step=step, actor=actor, detail=detail))


async def _find_by_ref(session: AsyncSession, ref: str) -> Recovery | None:
    return await session.scalar(
        select(Recovery).where(Recovery.razorpay_recovery_ref == ref)
    )


async def _find_by_subscription(session: AsyncSession, subscription_id: str) -> Recovery | None:
    return await session.scalar(
        select(Recovery)
        .where(Recovery.razorpay_subscription_id == subscription_id,
               Recovery.status.in_([RecoveryStatus.IN_PROGRESS.value, RecoveryStatus.PENDING.value]))
        .order_by(Recovery.created_at.desc())
    )


async def _find_by_original_payment(session: AsyncSession, payment_id: str) -> Recovery | None:
    return await session.scalar(
        select(Recovery).where(Recovery.razorpay_payment_id == payment_id)
    )


async def handle_close_event(event_type: str, payload: dict[str, Any]) -> dict:
    """Route a success/terminal webhook to the right closer. Returns a small
    dict summarizing what was done for observability."""
    async with SessionLocal() as session:
        p = payload.get("payload") or {}

        if event_type == "payment_link.paid":
            link = (p.get("payment_link") or {}).get("entity") or {}
            pay = (p.get("payment") or {}).get("entity") or {}
            ref = link.get("id")
            if not ref:
                return {"skipped": "no link id"}
            rec = await _find_by_ref(session, ref)
            if not rec:
                return {"skipped": "no matching recovery for link", "ref": ref}
            if rec.status == RecoveryStatus.RECOVERED.value:
                return {"noop": "already recovered", "recovery_id": rec.id}
            rec.status = RecoveryStatus.RECOVERED.value
            rec.recovered_amount_paise = int(pay.get("amount") or rec.amount_paise)
            _audit(session, rec.id, "closed_by_payment_link_paid", "razorpay", {
                "link_id": ref, "payment_id": pay.get("id"),
                "amount": rec.recovered_amount_paise,
            })
            await session.commit()
            return {"closed": rec.id, "via": "payment_link.paid"}

        if event_type == "payment.captured":
            pay = (p.get("payment") or {}).get("entity") or {}
            ref = pay.get("order_id")
            if not ref:
                return {"skipped": "no order id"}
            rec = await _find_by_ref(session, ref)
            if not rec:
                return {"skipped": "no matching recovery for order", "ref": ref}
            if rec.status == RecoveryStatus.RECOVERED.value:
                return {"noop": "already recovered", "recovery_id": rec.id}
            rec.status = RecoveryStatus.RECOVERED.value
            rec.recovered_amount_paise = int(pay.get("amount") or rec.amount_paise)
            _audit(session, rec.id, "closed_by_payment_captured", "razorpay", {
                "order_id": ref, "payment_id": pay.get("id"),
                "amount": rec.recovered_amount_paise,
            })
            await session.commit()
            return {"closed": rec.id, "via": "payment.captured"}

        if event_type in {"subscription.halted", "subscription.completed"}:
            sub = (p.get("subscription") or {}).get("entity") or {}
            sub_id = sub.get("id")
            if not sub_id:
                return {"skipped": "no subscription id"}
            rec = await _find_by_subscription(session, sub_id)
            if not rec:
                return {"skipped": "no open recovery for subscription", "ref": sub_id}
            terminal = RecoveryStatus.LOST if event_type == "subscription.halted" else RecoveryStatus.RECOVERED
            rec.status = terminal.value
            if terminal is RecoveryStatus.RECOVERED:
                rec.recovered_amount_paise = rec.amount_paise
            _audit(session, rec.id, f"closed_by_{event_type.replace('.', '_')}", "razorpay", {
                "subscription_id": sub_id, "final_status": terminal.value,
            })
            await session.commit()
            return {"closed": rec.id, "via": event_type}

        if event_type == "refund.processed":
            refund = (p.get("refund") or {}).get("entity") or {}
            pay_id = refund.get("payment_id")
            if not pay_id:
                return {"skipped": "no payment id"}
            rec = await _find_by_original_payment(session, pay_id)
            if not rec or rec.status != RecoveryStatus.RECOVERED.value:
                return {"skipped": "no recovered row to retract", "ref": pay_id}
            rec.status = RecoveryStatus.LOST.value
            rec.recovered_amount_paise = 0
            _audit(session, rec.id, "retracted_by_refund", "razorpay", {
                "refund_id": refund.get("id"), "payment_id": pay_id,
                "amount": refund.get("amount"),
            })
            await session.commit()
            return {"retracted": rec.id, "via": "refund.processed"}

        return {"ignored": event_type}


CLOSE_EVENT_TYPES = {
    "payment_link.paid",
    "payment.captured",
    "subscription.halted",
    "subscription.completed",
    "refund.processed",
}
