"""Semantic memory over past successful recoveries — RAG for actions.

For each new failure, embed the error_description (TF-IDF), retrieve the
k-nearest past SUCCESSFUL recoveries by cosine similarity, and return the
distribution of actions that worked for them. The bandit consumes this as an
additional per-decision prior — "what worked for similar failures on this
merchant historically?"

TF-IDF is deliberate: it's real semantic feature-vector search (not string
matching), fast, zero external dependencies, and interpretable. At production
scale swap in sentence-transformers or Gemini embeddings — the API stays
identical because we return the same `MemoryHits` shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import RecoveryMemory


@dataclass
class MemoryHits:
    hits: list[dict] = field(default_factory=list)  # [{recovery_id, cohort, similarity, action}]
    action_scores: dict[str, float] = field(default_factory=dict)  # normalized

    def to_dict(self) -> dict:
        return {
            "hits": self.hits,
            "action_scores": self.action_scores,
            "n_hits": len(self.hits),
        }


async def record(
    session: AsyncSession, *, recovery_id: int, cohort: str,
    text: str, action_taken: str, succeeded: bool,
) -> None:
    """Store one experience for future retrieval. Only successes become priors,
    but we log failures too so the memory has calibration data."""
    session.add(RecoveryMemory(
        recovery_id=recovery_id, cohort=cohort, text=(text or "")[:1024],
        action_taken=action_taken, succeeded=succeeded,
    ))


async def retrieve(
    session: AsyncSession, *, cohort: str, text: str, k: int = 5, min_sim: float = 0.15,
) -> MemoryHits:
    """Find k-nearest past SUCCESSFUL recoveries in this cohort by cosine
    similarity of TF-IDF features on error_description. Returns aggregated
    action-vote distribution weighted by similarity."""
    if not text:
        return MemoryHits()

    rows = (await session.execute(
        select(RecoveryMemory.recovery_id, RecoveryMemory.text,
               RecoveryMemory.action_taken, RecoveryMemory.cohort)
        .where(RecoveryMemory.cohort == cohort,
               RecoveryMemory.succeeded.is_(True))
        .order_by(RecoveryMemory.id.desc()).limit(500)  # cap the corpus per query
    )).all()
    if not rows:
        return MemoryHits()

    corpus = [text] + [r[1] for r in rows]
    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=2000).fit(corpus)
        mat = vec.transform(corpus)
        sims = cosine_similarity(mat[0:1], mat[1:]).ravel()
    except ValueError:
        return MemoryHits()

    idx = np.argsort(-sims)[:k]
    hits = []
    action_weight: dict[str, float] = {}
    for i in idx:
        s = float(sims[i])
        if s < min_sim:
            continue
        rid, rtext, action, _c = rows[i]
        hits.append({"recovery_id": rid, "similarity": s, "action": action, "cohort": _c})
        action_weight[action] = action_weight.get(action, 0.0) + s

    total = sum(action_weight.values()) or 1.0
    action_scores = {a: w / total for a, w in action_weight.items()}
    return MemoryHits(hits=hits, action_scores=action_scores)
