"""Realistic failed-payment scenario generator.

We can't hit a real merchant's failure volume in test mode, so we synthesize
webhook payloads matching Razorpay's real schema plus a distribution of failure
cohorts calibrated to public benchmarks. Each scenario has a ground-truth
cohort label so the classifier's precision can be measured.
"""
from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from typing import Any

# Cohort distribution roughly modeled on Indian fintech public benchmarks.
# Not exact — but stable so metric deltas across runs are meaningful.
COHORT_MIX = [
    ("insufficient_funds", 0.28, "BAD_REQUEST_ERROR", "insufficient_funds",
     "Payment failed due to insufficient funds in account"),
    ("bank_downtime", 0.22, "GATEWAY_ERROR", "bank_error",
     "Bank is down for maintenance. Please try after some time."),
    ("network_timeout", 0.15, "GATEWAY_ERROR", "network_error",
     "Payment request timed out"),
    ("auth_expired", 0.10, "BAD_REQUEST_ERROR", "auth_expired",
     "Authentication mandate expired for this subscription"),
    ("card_declined", 0.10, "BAD_REQUEST_ERROR", "payment_failed",
     "Card declined by issuing bank"),
    ("upi_psp_error", 0.08, "BAD_REQUEST_ERROR", "upi_psp_error",
     "UPI PSP returned error, please retry"),
    ("risk_declined", 0.05, "BAD_REQUEST_ERROR", "risk_check_failed",
     "Transaction blocked by risk checks"),
    ("unknown", 0.02, None, None,
     "Unexpected error"),
]


@dataclass
class Scenario:
    ground_truth_cohort: str
    payload: dict[str, Any]


def _pick_cohort() -> tuple[str, str | None, str | None, str]:
    r = random.random()
    acc = 0.0
    for name, weight, code, reason, desc in COHORT_MIX:
        acc += weight
        if r <= acc:
            return name, code, reason, desc
    return COHORT_MIX[-1][0], COHORT_MIX[-1][2], COHORT_MIX[-1][3], COHORT_MIX[-1][4]


def _amount_paise() -> int:
    return random.choice([9900, 19900, 49900, 99900, 249900, 499900, 999900])


def generate_scenario(rng_seed: int | None = None) -> Scenario:
    if rng_seed is not None:
        random.seed(rng_seed)
    cohort, code, reason, desc = _pick_cohort()
    pid = f"pay_{secrets.token_hex(6)}"
    oid = f"order_{secrets.token_hex(6)}"
    event_id = f"evt_{secrets.token_hex(8)}"
    # ~30% of failures are subscription-triggered — realistic mix for a mid-market
    # SaaS merchant on Razorpay. Subscription events carry a subscription_id
    # so the /subscriptions vertical view can filter by it.
    is_subscription = random.random() < 0.30
    entity = {
        "id": pid,
        "order_id": oid,
        "amount": _amount_paise(),
        "currency": "INR",
        "status": "failed",
        "method": random.choice(["upi", "card", "netbanking"]),
        "error_code": code,
        "error_reason": reason,
        "error_description": desc,
        "notes": {"customer_id": f"cust_{secrets.token_hex(4)}"},
    }
    event_type = "payment.failed"
    if is_subscription:
        entity["subscription_id"] = f"sub_{secrets.token_hex(6)}"
        event_type = "subscription.charged.failed"
    payload = {
        "id": event_id,
        "event": event_type,
        "contains": ["payment"],
        "simulated": True,
        "payload": {"payment": {"entity": entity}},
    }
    return Scenario(ground_truth_cohort=cohort, payload=payload)


def generate_batch(n: int) -> list[Scenario]:
    return [generate_scenario() for _ in range(n)]
