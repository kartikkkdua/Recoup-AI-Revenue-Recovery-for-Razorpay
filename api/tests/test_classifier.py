import asyncio

from app.classifier import classify
from app.db import FailureCohort


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_insufficient_funds_via_rule():
    payload = {
        "error_code": "BAD_REQUEST_ERROR",
        "error_reason": "insufficient_funds",
        "error_description": "no balance",
    }
    result = _run(classify(payload))
    assert result.cohort == FailureCohort.INSUFFICIENT_FUNDS
    assert result.source == "rules"
    assert result.confidence >= 0.9


def test_bank_downtime_via_rule():
    payload = {
        "error_code": "GATEWAY_ERROR",
        "error_reason": "bank_error",
        "error_description": "issuer bank offline",
    }
    result = _run(classify(payload))
    assert result.cohort == FailureCohort.BANK_DOWNTIME


def test_falls_back_to_keyword_match():
    payload = {
        "error_code": None,
        "error_reason": None,
        "error_description": "Payment request timed out at gateway",
    }
    result = _run(classify(payload))
    assert result.cohort == FailureCohort.NETWORK_TIMEOUT
    assert result.source == "keyword"


def test_unknown_when_no_signal():
    payload = {"error_code": None, "error_reason": None, "error_description": ""}
    result = _run(classify(payload))
    assert result.cohort == FailureCohort.UNKNOWN
