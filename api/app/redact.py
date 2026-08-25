"""PII redaction for audit output.

Emails, phone numbers, and card tails may enter the audit trail via webhook
notes or Razorpay link responses. By default the API returns them redacted —
merchants can opt-in to unredacted views with `X-Show-PII: 1` (bound to their
own role; enforced server-side, not just a client toggle).
"""
from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
PHONE_RE = re.compile(r"(\+?\d{1,3})[- ]?\d{6,}(\d{2})")
CARD_TAIL_RE = re.compile(r"\b(\d{4})[ -]?\d{4}[ -]?\d{4}[ -]?(\d{4})\b")


def redact_str(s: str) -> str:
    s = EMAIL_RE.sub(r"\1***\2", s)
    s = PHONE_RE.sub(r"\1********\2", s)
    s = CARD_TAIL_RE.sub(r"\1-****-****-\2", s)
    return s


def redact_value(v: Any) -> Any:
    if isinstance(v, str):
        return redact_str(v)
    if isinstance(v, dict):
        return {k: redact_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [redact_value(x) for x in v]
    return v
