from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import Recovery, get_session
from app.redact import redact_value

router = APIRouter()


@router.get("")
async def list_recoveries(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    cohort: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Recovery).order_by(Recovery.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(Recovery.status == status)
    if cohort:
        stmt = stmt.where(Recovery.cohort == cohort)
    rows = (await session.scalars(stmt)).all()
    return {
        "items": [
            {
                "id": r.id,
                "payment_id": r.razorpay_payment_id,
                "order_id": r.razorpay_order_id,
                "amount_paise": r.amount_paise,
                "recovered_paise": r.recovered_amount_paise,
                "currency": r.currency,
                "cohort": r.cohort,
                "status": r.status,
                "attempts": r.attempts,
                "created_at": r.created_at.isoformat(),
                "error_code": r.original_error_code,
                "error_description": r.original_error_description,
            }
            for r in rows
        ]
    }


@router.get("/{recovery_id}")
async def get_recovery(
    recovery_id: int,
    x_show_pii: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Recovery).options(selectinload(Recovery.audit)).where(Recovery.id == recovery_id)
    r = await session.scalar(stmt)
    if not r:
        raise HTTPException(status_code=404, detail="not found")
    # Decision context: distill the audit trail into the "why" summary the
    # dashboard renders above the raw log. This is what a merchant sees first
    # when they click into a recovery.
    classify_audit = next((a for a in r.audit if a.step == "classified"), None)
    decision_audit = next((a for a in r.audit if a.step == "decision_probability"), None)
    ml_audit = next((a for a in r.audit if a.step == "ml_decision"), None)
    gate_audit = next(
        (a for a in r.audit if a.step in {"rate_limited", "deferred_low_success_window",
                                          "circuit_open_deferred"}),
        None,
    )
    decision_context = {
        "classification": (classify_audit.detail if classify_audit else None),
        "probability": (decision_audit.detail if decision_audit else None),
        "ml": (ml_audit.detail if ml_audit else None),
        "gate_triggered": ({"step": gate_audit.step, **gate_audit.detail} if gate_audit else None),
        "strategy_reason": (r.strategy or {}).get("reason"),
    }

    show_pii = x_show_pii == "1"
    # Strip underscore-prefixed strategy keys (internal-only) before returning.
    public_strategy = None
    if r.strategy:
        public_strategy = {k: v for k, v in r.strategy.items() if not k.startswith("_")}

    def maybe(v):
        return v if show_pii else redact_value(v)

    body = {
        "id": r.id,
        "payment_id": r.razorpay_payment_id,
        "order_id": r.razorpay_order_id,
        "subscription_id": r.razorpay_subscription_id,
        "customer_id": r.merchant_customer_id,
        "amount_paise": r.amount_paise,
        "recovered_paise": r.recovered_amount_paise,
        "currency": r.currency,
        "cohort": r.cohort,
        "status": r.status,
        "attempts": r.attempts,
        "gateway_fee_paise": r.gateway_fee_paise,
        "strategy": public_strategy,
        "strategy_mode": r.strategy_mode,
        "decision_context": maybe(decision_context),
        "error_code": r.original_error_code,
        "error_description": r.original_error_description,
        "created_at": r.created_at.isoformat(),
        "updated_at": r.updated_at.isoformat(),
        "audit": [
            {
                "step": a.step,
                "actor": a.actor,
                "detail": maybe(a.detail),
                "at": a.created_at.isoformat(),
            }
            for a in r.audit
        ],
        "pii_redacted": not show_pii,
    }
    return body
