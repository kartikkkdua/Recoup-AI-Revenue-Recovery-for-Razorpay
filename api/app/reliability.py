"""In-process reliability primitives — circuit breaker, per-customer rate
limiter, and duplicate-event counters. These are deliberately in-process; at
merchant scale they'd move to Redis. The API surface stays the same.
"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque


# ------------------ Circuit breaker ------------------

@dataclass
class CircuitBreaker:
    fail_threshold: int = 5
    open_seconds: float = 30.0
    _consecutive_failures: int = 0
    _opened_at: float = 0.0
    _state: str = "closed"  # closed | open | half_open
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def before_call(self) -> bool:
        """Return True if the call may proceed; False if circuit is open."""
        async with self._lock:
            if self._state == "open":
                if time.monotonic() - self._opened_at >= self.open_seconds:
                    self._state = "half_open"
                    return True
                return False
            return True

    async def on_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0
            self._state = "closed"

    async def on_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.fail_threshold:
                self._state = "open"
                self._opened_at = time.monotonic()

    def snapshot(self) -> dict:
        return {
            "state": self._state,
            "consecutive_failures": self._consecutive_failures,
            "opens_remaining_s": max(
                0.0, self.open_seconds - (time.monotonic() - self._opened_at)
            ) if self._state == "open" else 0.0,
        }


razorpay_circuit = CircuitBreaker()


# ------------------ Per-customer rate limiter ------------------

class CustomerRateLimiter:
    """Sliding window: at most `max_attempts` recovery actions per customer per
    `window_seconds`. Prevents the agent from spamming the same customer with
    retries or dunning messages when their card is genuinely dead."""

    def __init__(self, max_attempts: int = 3, window_seconds: int = 24 * 3600) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._events: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._denials = 0

    async def check_and_record(self, customer_id: str | None) -> tuple[bool, int]:
        """Returns (allowed, remaining_after_this_call). If no customer_id, always allowed."""
        if not customer_id:
            return True, self.max_attempts
        now = time.time()
        cutoff = now - self.window_seconds
        async with self._lock:
            dq = self._events[customer_id]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_attempts:
                self._denials += 1
                return False, 0
            dq.append(now)
            return True, self.max_attempts - len(dq)

    def snapshot(self) -> dict:
        return {
            "max_per_customer_per_24h": self.max_attempts,
            "customers_tracked": len(self._events),
            "denials_total": self._denials,
        }


rate_limiter = CustomerRateLimiter()


# ------------------ Duplicate counter ------------------

class DuplicateCounter:
    def __init__(self) -> None:
        self._n = 0
        self._lock = asyncio.Lock()

    async def bump(self) -> int:
        async with self._lock:
            self._n += 1
            return self._n

    def value(self) -> int:
        return self._n


duplicate_counter = DuplicateCounter()


# ------------------ Time-of-day retry gate ------------------

# Hours-of-day (IST, 24h) where success rates are historically weakest.
# Retries scheduled into these windows get deferred to the next favorable hour.
# Sourced from public Indian bank-downtime posts + UPI PSP dashboards;
# tune from learned rates once we have volume.
LOW_SUCCESS_HOURS_IST = set(range(23, 24)) | set(range(0, 6))  # 11pm–6am IST


def is_low_success_hour_ist(now_utc_hour: int) -> bool:
    ist_hour = (now_utc_hour + 5) % 24  # simplified IST (+5:30 rounded to +5 for hour bucket)
    return ist_hour in LOW_SUCCESS_HOURS_IST


def next_favorable_hour_ist(now_utc_hour: int) -> int:
    """Return hours-to-wait until the next hour NOT in the low-success window."""
    for delta in range(1, 25):
        h_utc = (now_utc_hour + delta) % 24
        if not is_low_success_hour_ist(h_utc):
            return delta
    return 0
