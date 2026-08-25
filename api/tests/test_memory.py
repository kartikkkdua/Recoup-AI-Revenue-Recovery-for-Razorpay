"""Semantic memory retrieves nearest past successful recoveries by TF-IDF."""
import pytest

from app import memory as memory_mod
from app.db import SessionLocal


@pytest.mark.asyncio
async def test_retrieves_similar_success_and_scores_action():
    async with SessionLocal() as s:
        # Seed: 3 similar successes for "retry", 1 unrelated success for "payment_link_dunning"
        for i in range(3):
            await memory_mod.record(s, recovery_id=100 + i, cohort="bank_downtime",
                                    text="Bank downtime — issuer offline retry later",
                                    action_taken="retry", succeeded=True)
        await memory_mod.record(s, recovery_id=200, cohort="bank_downtime",
                                text="Totally different unrelated failure text about mangoes",
                                action_taken="payment_link_dunning", succeeded=True)
        await s.commit()

        hits = await memory_mod.retrieve(
            s, cohort="bank_downtime",
            text="Bank downtime issuer offline retry",
            k=5,
        )
    assert len(hits.hits) >= 3
    top = max(hits.action_scores.items(), key=lambda kv: kv[1])
    assert top[0] == "retry"


@pytest.mark.asyncio
async def test_ignores_failures_in_retrieval():
    async with SessionLocal() as s:
        await memory_mod.record(s, recovery_id=300, cohort="card_declined",
                                text="card declined by issuing bank", action_taken="retry",
                                succeeded=False)
        await memory_mod.record(s, recovery_id=301, cohort="card_declined",
                                text="card declined by issuing bank", action_taken="rail_switch_link",
                                succeeded=True)
        await s.commit()
        hits = await memory_mod.retrieve(
            s, cohort="card_declined",
            text="card declined issuing bank",
        )
    # Only the successful action counts toward action_scores
    assert list(hits.action_scores.keys()) == ["rail_switch_link"]


@pytest.mark.asyncio
async def test_empty_corpus_returns_no_hits():
    async with SessionLocal() as s:
        hits = await memory_mod.retrieve(s, cohort="unknown", text="anything")
    assert hits.hits == []
    assert hits.action_scores == {}


@pytest.mark.asyncio
async def test_empty_text_returns_no_hits():
    async with SessionLocal() as s:
        hits = await memory_mod.retrieve(s, cohort="bank_downtime", text="")
    assert hits.hits == []
