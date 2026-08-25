"""Test fixtures — fresh SQLite DB per test session, deterministic secrets."""
import os
import pathlib
import tempfile

import pytest

# Force isolated env BEFORE app modules import Settings.
_tmpdir = tempfile.mkdtemp(prefix="recoup_tests_")
_dbfile = pathlib.Path(_tmpdir) / "test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_dbfile}")
os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_placeholder")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "placeholder")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "test_secret_hunter2")
os.environ.setdefault("GEMINI_API_KEY", "")


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Wipe the tables between tests so state doesn't leak."""
    from app.db import Base, engine, init_db

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()

    # Reset the in-process reliability primitives too.
    from app.reliability import CustomerRateLimiter, DuplicateCounter, rate_limiter, duplicate_counter
    rate_limiter._events.clear()
    rate_limiter._denials = 0
    duplicate_counter._n = 0

    yield
