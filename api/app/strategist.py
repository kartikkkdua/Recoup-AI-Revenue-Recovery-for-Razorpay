"""Strategist — picks a deterministic recovery plan per failure cohort.

Every cohort now has an explicit playbook. Merchant Rules can override the
defaults. `build_naive_strategy` returns the counterfactual — retry everything
3x on the same rail — so the dashboard can show agent-vs-naive lift.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import FailureCohort, Rule


@dataclass
class Strategy:
    action: str  # retry | payment_link_dunning | payday_retry | tokenization_link |
                 # rail_switch_link | human_review | abandon
    rails: list[str] = field(default_factory=list)
    backoff_seconds: list[int] = field(default_factory=list)
    max_attempts: int = 3
    dunning_channels: list[str] = field(default_factory=list)
    payday_windows_hours: list[int] = field(default_factory=list)
    reason: str = ""


DEFAULT_STRATEGIES: dict[FailureCohort, Strategy] = {
    FailureCohort.INSUFFICIENT_FUNDS: Strategy(
        action="payday_retry",
        rails=["upi", "netbanking"],
        # target the classic Indian payday cycles: 24h, 3d, next 1st/15th
        backoff_seconds=[86400, 259200],
        payday_windows_hours=[24, 72, 240],
        max_attempts=3,
        dunning_channels=["whatsapp", "email"],
        reason="wallet empty; nudge + retry aligned to salary cycles via cheaper rails",
    ),
    FailureCohort.BANK_DOWNTIME: Strategy(
        action="retry",
        rails=["same"],
        backoff_seconds=[60, 300, 900],
        max_attempts=4,
        dunning_channels=[],
        reason="issuer transient; short-window retry on same rail",
    ),
    FailureCohort.AUTH_EXPIRED: Strategy(
        action="tokenization_link",
        rails=["card", "upi"],
        backoff_seconds=[0],
        max_attempts=1,
        dunning_channels=["email", "whatsapp"],
        reason="mandate/token expired; send re-tokenization link, one-tap resave",
    ),
    FailureCohort.RISK_DECLINED: Strategy(
        action="human_review",
        rails=[],
        backoff_seconds=[],
        max_attempts=0,
        dunning_channels=[],
        reason="declined by risk; queue for manual review, do not auto-retry",
    ),
    FailureCohort.NETWORK_TIMEOUT: Strategy(
        action="retry",
        rails=["same"],
        backoff_seconds=[30, 120],
        max_attempts=2,
        dunning_channels=[],
        reason="network hiccup; fast retry on same rail",
    ),
    FailureCohort.CARD_DECLINED: Strategy(
        action="rail_switch_link",
        rails=["upi", "netbanking"],
        backoff_seconds=[1800, 86400],
        max_attempts=2,
        dunning_channels=["email", "whatsapp"],
        reason="issuer refused card; send link with UPI as default rail",
    ),
    FailureCohort.UPI_PSP_ERROR: Strategy(
        action="retry",
        rails=["upi_alt", "card"],
        backoff_seconds=[120, 600],
        max_attempts=2,
        dunning_channels=[],
        reason="upi PSP flaky; retry on alt PSP then fall back to card",
    ),
    FailureCohort.UNKNOWN: Strategy(
        action="human_review",
        reason="cohort unresolved; do not auto-retry money actions",
    ),
}


NAIVE_STRATEGY = Strategy(
    action="retry",
    rails=["same"],
    backoff_seconds=[60, 300, 900],
    max_attempts=3,
    dunning_channels=[],
    reason="naive baseline: retry every failure 3x on the same rail",
)


async def build_strategy(cohort: FailureCohort, session: AsyncSession) -> Strategy:
    default = DEFAULT_STRATEGIES.get(cohort, DEFAULT_STRATEGIES[FailureCohort.UNKNOWN])
    rule = await session.scalar(select(Rule).where(Rule.cohort == cohort.value))
    if not rule or not rule.enabled:
        return default
    return Strategy(
        action=default.action,
        rails=list(rule.preferred_rails or default.rails),
        backoff_seconds=list(rule.backoff_seconds or default.backoff_seconds),
        max_attempts=int(rule.max_attempts or default.max_attempts),
        dunning_channels=list(rule.dunning_channels or default.dunning_channels),
        payday_windows_hours=list(default.payday_windows_hours),
        reason=default.reason + " (merchant-tuned)",
    )


def build_naive_strategy(_cohort: FailureCohort) -> Strategy:
    return NAIVE_STRATEGY


def to_dict(strategy: Strategy) -> dict:
    return asdict(strategy)
