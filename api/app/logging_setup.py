"""Structured JSON logging with a request-scoped trace_id contextvar.

Every log line downstream of a webhook or an ML decision carries
`trace_id`, `event_id`, `recovery_id`, `customer_id` — so an SRE can
`grep trace_id=abc123` and get the whole recovery's log trail. Formatter
emits one JSON object per line, ready for Loki / CloudWatch / Datadog.
"""
from __future__ import annotations

import contextvars
import json
import logging
import secrets
import time

_trace: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")
_event: contextvars.ContextVar[str] = contextvars.ContextVar("event_id", default="-")
_recovery: contextvars.ContextVar[str] = contextvars.ContextVar("recovery_id", default="-")
_customer: contextvars.ContextVar[str] = contextvars.ContextVar("customer_id", default="-")


def new_trace() -> str:
    tid = secrets.token_hex(6)
    _trace.set(tid)
    return tid


def set_context(*, event_id: str | None = None, recovery_id: int | str | None = None,
                customer_id: str | None = None) -> None:
    if event_id: _event.set(event_id)
    if recovery_id: _recovery.set(str(recovery_id))
    if customer_id: _customer.set(customer_id)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": round(time.time(), 3),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": _trace.get(),
            "event_id": _event.get(),
            "recovery_id": _recovery.get(),
            "customer_id": _customer.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"))


def configure(json_output: bool = False, level: int = logging.INFO) -> None:
    """json_output=True for production; False keeps human-readable dev logs."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    if json_output:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
