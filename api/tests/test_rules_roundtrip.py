"""End-to-end proof that a rule override written via the API is actually
picked up by the strategist on the next classification."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.db import FailureCohort, SessionLocal
from app.main import app
from app.strategist import DEFAULT_STRATEGIES, build_strategy


@pytest.mark.asyncio
async def test_put_override_then_strategist_reads_it():
    cohort = FailureCohort.BANK_DOWNTIME.value
    async with SessionLocal() as s:
        default = await build_strategy(FailureCohort(cohort), s)
    assert default.max_attempts == DEFAULT_STRATEGIES[FailureCohort.BANK_DOWNTIME].max_attempts

    override = {
        "cohort": cohort,
        "max_attempts": 7,
        "backoff_seconds": [10, 20, 30, 40, 50, 60, 70],
        "preferred_rails": ["upi_alt"],
        "dunning_channels": ["whatsapp"],
        "enabled": True,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put(f"/api/rules/{cohort}", json=override)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    async with SessionLocal() as s:
        loaded = await build_strategy(FailureCohort(cohort), s)
    assert loaded.max_attempts == 7
    assert loaded.backoff_seconds == [10, 20, 30, 40, 50, 60, 70]
    assert loaded.rails == ["upi_alt"]
    assert loaded.dunning_channels == ["whatsapp"]
    assert "merchant-tuned" in loaded.reason


@pytest.mark.asyncio
async def test_delete_resets_to_default():
    cohort = FailureCohort.CARD_DECLINED.value
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put(f"/api/rules/{cohort}", json={
            "cohort": cohort, "max_attempts": 9, "backoff_seconds": [1],
            "preferred_rails": ["x"], "dunning_channels": [], "enabled": True,
        })
        # confirm override took effect
        async with SessionLocal() as s:
            s1 = await build_strategy(FailureCohort(cohort), s)
        assert s1.max_attempts == 9

        d = await c.delete(f"/api/rules/{cohort}")
    assert d.status_code == 200
    assert d.json().get("reset") == cohort

    async with SessionLocal() as s:
        after = await build_strategy(FailureCohort(cohort), s)
    assert after.max_attempts == DEFAULT_STRATEGIES[FailureCohort.CARD_DECLINED].max_attempts


@pytest.mark.asyncio
async def test_disabled_override_ignored():
    cohort = FailureCohort.NETWORK_TIMEOUT.value
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put(f"/api/rules/{cohort}", json={
            "cohort": cohort, "max_attempts": 99, "backoff_seconds": [999],
            "preferred_rails": ["ignore_me"], "dunning_channels": [], "enabled": False,
        })
    async with SessionLocal() as s:
        loaded = await build_strategy(FailureCohort(cohort), s)
    # disabled override → default
    assert loaded.max_attempts == DEFAULT_STRATEGIES[FailureCohort.NETWORK_TIMEOUT].max_attempts


@pytest.mark.asyncio
async def test_get_reflects_saved_override():
    cohort = FailureCohort.AUTH_EXPIRED.value
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.put(f"/api/rules/{cohort}", json={
            "cohort": cohort, "max_attempts": 4, "backoff_seconds": [0, 60],
            "preferred_rails": ["upi"], "dunning_channels": ["email"], "enabled": True,
        })
        r = await c.get("/api/rules")
    assert r.status_code == 200
    row = next(i for i in r.json()["items"] if i["cohort"] == cohort)
    assert row["override"] is not None
    assert row["override"]["max_attempts"] == 4
    assert row["override"]["preferred_rails"] == ["upi"]


@pytest.mark.asyncio
async def test_unknown_cohort_rejected():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.put("/api/rules/not_a_real_cohort", json={
            "cohort": "not_a_real_cohort", "max_attempts": 1, "backoff_seconds": [],
            "preferred_rails": [], "dunning_channels": [], "enabled": True,
        })
    assert r.status_code == 400
