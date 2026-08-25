"""Failure classifier.

Deterministic rules run first. LLM is called only when rules return UNKNOWN
and an Anthropic key is configured. LLM output is treated as a suggestion —
it never causes a charge on its own; it only tags a cohort for strategy lookup.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings
from app.db import FailureCohort


RULE_MAP: dict[tuple[str | None, str | None], FailureCohort] = {
    ("BAD_REQUEST_ERROR", "insufficient_funds"): FailureCohort.INSUFFICIENT_FUNDS,
    ("BAD_REQUEST_ERROR", "payment_failed"): FailureCohort.CARD_DECLINED,
    ("GATEWAY_ERROR", "bank_error"): FailureCohort.BANK_DOWNTIME,
    ("GATEWAY_ERROR", "gateway_technical_error"): FailureCohort.BANK_DOWNTIME,
    ("GATEWAY_ERROR", "network_error"): FailureCohort.NETWORK_TIMEOUT,
    ("BAD_REQUEST_ERROR", "auth_expired"): FailureCohort.AUTH_EXPIRED,
    ("BAD_REQUEST_ERROR", "mandate_expired"): FailureCohort.AUTH_EXPIRED,
    ("BAD_REQUEST_ERROR", "risk_check_failed"): FailureCohort.RISK_DECLINED,
    ("BAD_REQUEST_ERROR", "upi_psp_error"): FailureCohort.UPI_PSP_ERROR,
}

DESCRIPTION_KEYWORDS: list[tuple[str, FailureCohort]] = [
    ("insufficient", FailureCohort.INSUFFICIENT_FUNDS),
    ("balance", FailureCohort.INSUFFICIENT_FUNDS),
    ("bank is down", FailureCohort.BANK_DOWNTIME),
    ("bank downtime", FailureCohort.BANK_DOWNTIME),
    ("issuer", FailureCohort.BANK_DOWNTIME),
    ("timeout", FailureCohort.NETWORK_TIMEOUT),
    ("timed out", FailureCohort.NETWORK_TIMEOUT),
    ("expired", FailureCohort.AUTH_EXPIRED),
    ("mandate", FailureCohort.AUTH_EXPIRED),
    ("risk", FailureCohort.RISK_DECLINED),
    ("declined", FailureCohort.CARD_DECLINED),
    ("upi", FailureCohort.UPI_PSP_ERROR),
    ("psp", FailureCohort.UPI_PSP_ERROR),
]


@dataclass
class Classification:
    cohort: FailureCohort
    source: str  # "rules" | "keyword" | "llm"
    confidence: float
    reasoning: str


def _rules_lookup(code: str | None, reason: str | None) -> FailureCohort | None:
    key = (code, reason)
    if key in RULE_MAP:
        return RULE_MAP[key]
    return None


def _keyword_lookup(description: str | None) -> FailureCohort | None:
    if not description:
        return None
    desc = description.lower()
    for kw, cohort in DESCRIPTION_KEYWORDS:
        if kw in desc:
            return cohort
    return None


async def _llm_classify(payload: dict[str, Any]) -> Classification | None:
    key = settings.gemini_api_key
    if not key or key.endswith("xxx") or len(key) < 20:
        return None
    prompt = (
        "Classify this Razorpay payment failure into exactly one cohort from: "
        + ", ".join(c.value for c in FailureCohort)
        + ". Respond ONLY with JSON: {\"cohort\": \"<cohort>\", \"confidence\": <0-1>, \"reasoning\": \"<short>\"}\n\n"
        + "Payment error payload:\n" + json.dumps(payload)[:2000]
    )
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.llm_model}:generateContent?key={key}"
    )
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                url,
                headers={"content-type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": 200,
                        "temperature": 0.0,
                        "responseMimeType": "application/json",
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
            cohort = FailureCohort(parsed["cohort"])
            return Classification(
                cohort=cohort,
                source="llm",
                confidence=float(parsed.get("confidence", 0.5)),
                reasoning=parsed.get("reasoning", "")[:400],
            )
    except Exception as exc:  # noqa: BLE001 — LLM is best-effort
        return Classification(
            cohort=FailureCohort.UNKNOWN,
            source="llm",
            confidence=0.0,
            reasoning=f"llm_failed: {exc.__class__.__name__}",
        )


async def classify(payment: dict[str, Any]) -> Classification:
    code = payment.get("error_code")
    reason = payment.get("error_reason")
    description = payment.get("error_description")

    rule_hit = _rules_lookup(code, reason)
    if rule_hit:
        return Classification(
            cohort=rule_hit,
            source="rules",
            confidence=0.99,
            reasoning=f"rule[{code}/{reason}]",
        )

    kw_hit = _keyword_lookup(description)
    if kw_hit:
        return Classification(
            cohort=kw_hit,
            source="keyword",
            confidence=0.75,
            reasoning=f"keyword_match on error_description",
        )

    llm_hit = await _llm_classify(payment)
    if llm_hit:
        return llm_hit

    return Classification(
        cohort=FailureCohort.UNKNOWN,
        source="rules",
        confidence=0.0,
        reasoning="no rule, keyword, or llm match",
    )
