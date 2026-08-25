"""The recovery agent — classifier → strategist → executor.

Wired to three reliability primitives:
- Per-customer rate limiter (no more than 3 recovery actions/customer/24h)
- Time-of-day gate (skips retries into historically low-success IST hours)
- Circuit breaker inside the Razorpay client (open on repeated 5xx)

And to a learning loop: each attempt's outcome updates a per-cohort × per-action
× per-hour rolling estimate. The strategist blends learned p with hardcoded
priors, so cold cohorts behave sensibly and hot ones adapt.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.classifier import classify
from app.db import (
    AuditEntry,
    FailureCohort,
    Recovery,
    RecoveryStatus,
    SessionLocal,
    WebhookEvent,
)
from app.learning import learned_p, record_outcome
from app.razorpay_client import CircuitOpenError, client
from app.reliability import is_low_success_hour_ist, next_favorable_hour_ist, rate_limiter
from app.strategist import Strategy, build_naive_strategy, build_strategy, to_dict

FEE_RETRY_ATTEMPT = 200
FEE_PAYMENT_LINK = 100
FEE_WHATSAPP_NUDGE = 50

AGENT_RETRY_P: dict[str, list[float]] = {
    FailureCohort.BANK_DOWNTIME.value: [0.25, 0.35, 0.30, 0.20],
    FailureCohort.NETWORK_TIMEOUT.value: [0.70, 0.45],
    FailureCohort.UPI_PSP_ERROR.value: [0.45, 0.35],
}

AGENT_LINK_P: dict[str, float] = {
    FailureCohort.INSUFFICIENT_FUNDS.value: 0.42,
    FailureCohort.AUTH_EXPIRED.value: 0.58,
    FailureCohort.CARD_DECLINED.value: 0.28,
}

NAIVE_RETRY_P: dict[str, list[float]] = {
    FailureCohort.BANK_DOWNTIME.value: [0.15, 0.10, 0.05],
    FailureCohort.NETWORK_TIMEOUT.value: [0.55, 0.15, 0.05],
    FailureCohort.UPI_PSP_ERROR.value: [0.20, 0.10, 0.05],
    FailureCohort.INSUFFICIENT_FUNDS.value: [0.02, 0.02, 0.02],
    FailureCohort.AUTH_EXPIRED.value: [0.01, 0.01, 0.01],
    FailureCohort.CARD_DECLINED.value: [0.03, 0.02, 0.01],
    FailureCohort.RISK_DECLINED.value: [0.00, 0.00, 0.00],
    FailureCohort.UNKNOWN.value: [0.05, 0.03, 0.02],
}


def _extract_payment(payload: dict[str, Any]) -> dict[str, Any] | None:
    return (payload.get("payload") or {}).get("payment", {}).get("entity")


def _audit(session: AsyncSession, recovery_id: int, step: str, actor: str, detail: dict) -> None:
    session.add(AuditEntry(recovery_id=recovery_id, step=step, actor=actor, detail=detail))


async def handle_event(event_row_id: int, *, mode: str = "agent") -> None:
    async with SessionLocal() as session:
        event = await session.get(WebhookEvent, event_row_id)
        if not event:
            return
        payload = event.payload or {}
        payment = _extract_payment(payload) or {}
        simulated = bool(payload.get("simulated"))

        # Passthrough customer contact from notes so the executor can send a
        # link to the real customer for live Razorpay demos.
        notes = payment.get("notes") or {}
        recovery = Recovery(
            razorpay_payment_id=payment.get("id"),
            razorpay_order_id=payment.get("order_id"),
            razorpay_subscription_id=payment.get("subscription_id"),
            merchant_customer_id=notes.get("customer_id"),
            amount_paise=int(payment.get("amount") or 0),
            currency=payment.get("currency") or "INR",
            cohort=FailureCohort.UNKNOWN.value,
            original_error_code=payment.get("error_code"),
            original_error_description=(payment.get("error_description") or "")[:512],
            status=RecoveryStatus.IN_PROGRESS.value,
            strategy_mode=mode,
        )
        session.add(recovery)
        await session.flush()

        _audit(session, recovery.id, "webhook_received", "razorpay",
               {"event_type": event.event_type, "payment_id": payment.get("id"),
                "simulated": simulated, "mode": mode})

        classification = await classify(payment)
        recovery.cohort = classification.cohort.value
        _audit(session, recovery.id, "classified", classification.source, {
            "cohort": classification.cohort.value,
            "confidence": classification.confidence,
            "reasoning": classification.reasoning,
        })

        # Rate limit: agent mode only. The naive baseline deliberately doesn't
        # rate-limit so the panel can see the difference.
        if mode == "agent":
            allowed, remaining = await rate_limiter.check_and_record(recovery.merchant_customer_id)
            if not allowed:
                recovery.status = RecoveryStatus.SKIPPED.value
                _audit(session, recovery.id, "rate_limited", "reliability",
                       {"reason": "customer already at cap in 24h window",
                        "customer_id": recovery.merchant_customer_id,
                        "cap_per_customer_24h": rate_limiter.max_attempts})
                await session.commit()
                return

        if mode == "naive":
            strategy = build_naive_strategy(classification.cohort)
        else:
            strategy = await build_strategy(classification.cohort, session)
        strategy_dict = to_dict(strategy)
        # Stash the incoming notes on the strategy dict (prefixed with _) so
        # the executor can reach them without another DB round-trip. Never
        # rendered on the dashboard because we hide underscore-prefixed keys.
        strategy_dict["_notes"] = {
            "contact": notes.get("contact"),
            "email": notes.get("email"),
            "name": notes.get("name"),
        }
        recovery.strategy = strategy_dict
        _audit(session, recovery.id, "strategy_chosen", "strategist",
               {"strategy": {k: v for k, v in strategy_dict.items() if not k.startswith("_")},
                "mode": mode})

        # Single commit per recovery — the interim commit here previously
        # ordered a Razorpay round-trip against a durable row, but since we
        # never expose mid-execution state to another process, it just cost
        # us an extra fsync per event. 2 → 1 commit = 2x throughput on WAL.
        outcome = await _execute(session, recovery, strategy, simulated=simulated, mode=mode)
        recovery.status = outcome.value
        await session.commit()


async def _execute(
    session: AsyncSession,
    recovery: Recovery,
    strategy: Strategy,
    *,
    simulated: bool,
    mode: str,
) -> RecoveryStatus:
    cohort = recovery.cohort

    if strategy.action in {"human_review", "abandon"}:
        _audit(session, recovery.id, "skipped", "executor",
               {"reason": strategy.reason, "action": strategy.action})
        return RecoveryStatus.SKIPPED

    # Time-of-day gate: only for cheap-retry strategies where success is
    # rail-dependent (bank downtime + UPI). Link-based recoveries are async, so
    # this doesn't apply — the customer opens the link on their schedule.
    if mode == "agent" and strategy.action == "retry":
        hour_utc = datetime.now(timezone.utc).hour
        if is_low_success_hour_ist(hour_utc):
            defer = next_favorable_hour_ist(hour_utc)
            _audit(session, recovery.id, "deferred_low_success_window", "reliability",
                   {"reason": "current IST hour historically low success for retries",
                    "defer_hours": defer,
                    "policy": "retry_gate_2300_0600_ist"})
            # In this simulated build we accept the deferral as a skip so the
            # metric surfaces it. In production this row would be requeued.
            return RecoveryStatus.SKIPPED

    if strategy.action == "retry":
        probs = (NAIVE_RETRY_P if mode == "naive" else AGENT_RETRY_P).get(cohort, [0.0])
        return await _do_retries(session, recovery, strategy, probs,
                                 simulated=simulated, mode=mode, learn_action="retry")

    if strategy.action == "payday_retry":
        try:
            nudge = await client.send_whatsapp_nudge(
                customer={"contact": "+919999999999"},
                amount_paise=recovery.amount_paise,
                short_url="https://rzp.io/i/sim_nudge",
                simulated=simulated,
            )
        except CircuitOpenError as exc:
            _audit(session, recovery.id, "circuit_open_deferred", "reliability",
                   {"reason": str(exc), "action": "whatsapp_nudge"})
            return RecoveryStatus.SKIPPED
        recovery.gateway_fee_paise += FEE_WHATSAPP_NUDGE
        _audit(session, recovery.id, "whatsapp_nudge_sent", "razorpay",
               {"nudge": nudge, "cost_paise": FEE_WHATSAPP_NUDGE})
        prior = AGENT_LINK_P.get(cohort, 0.4)
        blended, obs_n, raw = await learned_p(session, cohort=cohort, action="payday_retry",
                                              prior=prior)
        return await _do_retries(session, recovery, strategy, [blended] * max(1, strategy.max_attempts),
                                 simulated=simulated, mode=mode, learn_action="payday_retry",
                                 prior_meta={"prior": prior, "learned_blended": blended,
                                             "observed_attempts": obs_n, "observed_p": raw})

    if strategy.action in {"payment_link_dunning", "tokenization_link", "rail_switch_link"}:
        rail_hint = strategy.rails[0] if strategy.rails else None
        # Extract customer contact from the webhook payload's notes so real
        # links reach the actual customer, not the +91-999... placeholder.
        notes = (recovery.strategy or {}).get("_notes") or {}
        customer = {
            "contact": notes.get("contact") or "+919999999999",
            "email": notes.get("email") or "sim@example.com",
            "name": notes.get("name") or "Customer",
        }
        try:
            link = await client.create_payment_link(
                amount_paise=recovery.amount_paise,
                currency=recovery.currency,
                customer=customer,
                simulated=simulated,
                rail_hint=rail_hint,
            )
        except CircuitOpenError as exc:
            _audit(session, recovery.id, "circuit_open_deferred", "reliability",
                   {"reason": str(exc), "action": strategy.action})
            return RecoveryStatus.SKIPPED
        recovery.attempts += 1
        recovery.gateway_fee_paise += FEE_PAYMENT_LINK
        recovery.razorpay_recovery_ref = link.get("id")
        _audit(session, recovery.id, f"{strategy.action}_created", "razorpay", {
            "link_id": link.get("id"), "short_url": link.get("short_url"),
            "channels": strategy.dunning_channels, "rail_hint": rail_hint,
            "cost_paise": FEE_PAYMENT_LINK,
        })
        # REAL Razorpay path: link is out; customer must click and pay. The
        # closer will flip status → RECOVERED on inbound payment_link.paid.
        # We leave the row as IN_PROGRESS so the dashboard shows the pending
        # dunning attempt honestly (not a fake win).
        if not simulated:
            _audit(session, recovery.id, "awaiting_customer_action", "executor",
                   {"link_id": link.get("id"), "short_url": link.get("short_url")})
            return RecoveryStatus.IN_PROGRESS

        prior = AGENT_LINK_P.get(cohort, 0.15)
        p, obs_n, raw = await learned_p(session, cohort=cohort, action=strategy.action, prior=prior)
        success = random.random() < p
        await record_outcome(session, cohort=cohort, action=strategy.action, success=success)
        _audit(session, recovery.id, "decision_probability", "strategist", {
            "prior": prior, "learned_blended": p,
            "observed_attempts": obs_n, "observed_p": raw,
        })
        if success:
            recovery.recovered_amount_paise = recovery.amount_paise
            _audit(session, recovery.id, "recovered", "executor",
                   {"via": strategy.action, "p_used": p})
            return RecoveryStatus.RECOVERED
        return RecoveryStatus.LOST

    return RecoveryStatus.SKIPPED


async def _do_retries(
    session: AsyncSession,
    recovery: Recovery,
    strategy: Strategy,
    probs: list[float],
    *,
    simulated: bool,
    mode: str,
    learn_action: str,
    prior_meta: dict | None = None,
) -> RecoveryStatus:
    attempts = min(strategy.max_attempts, len(probs))
    if prior_meta:
        _audit(session, recovery.id, "decision_probability", "strategist", prior_meta)
    for i in range(1, attempts + 1):
        recovery.attempts += 1
        recovery.gateway_fee_paise += FEE_RETRY_ATTEMPT
        try:
            result = await client.retry_order(
                order_id=recovery.razorpay_order_id or "",
                amount_paise=recovery.amount_paise,
                simulated=simulated,
            )
        except CircuitOpenError as exc:
            _audit(session, recovery.id, "circuit_open_deferred", "reliability",
                   {"reason": str(exc), "attempt": i})
            return RecoveryStatus.SKIPPED
        # Track the new order id so payment.captured can close this recovery.
        if not simulated and result.get("id"):
            recovery.razorpay_recovery_ref = result.get("id")
        p = probs[i - 1] if i - 1 < len(probs) else probs[-1]
        _audit(session, recovery.id, f"{learn_action}_attempt_{i}", "razorpay", {
            "rail": strategy.rails[0] if strategy.rails else "same",
            "result": result,
            "p_used": p,
            "cost_paise": FEE_RETRY_ATTEMPT,
        })
        if not simulated:
            _audit(session, recovery.id, "awaiting_capture", "executor",
                   {"new_order_id": result.get("id"), "attempt": i})
            return RecoveryStatus.IN_PROGRESS
        success = random.random() < p
        if mode == "agent":
            await record_outcome(session, cohort=recovery.cohort, action=learn_action, success=success)
        if success:
            recovery.recovered_amount_paise = recovery.amount_paise
            _audit(session, recovery.id, "recovered", "executor",
                   {"via": learn_action, "attempt": i, "p_used": p})
            return RecoveryStatus.RECOVERED
    return RecoveryStatus.LOST
