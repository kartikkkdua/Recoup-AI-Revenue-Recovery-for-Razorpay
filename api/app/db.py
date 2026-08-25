from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FailureCohort(str, Enum):
    INSUFFICIENT_FUNDS = "insufficient_funds"
    BANK_DOWNTIME = "bank_downtime"
    AUTH_EXPIRED = "auth_expired"
    RISK_DECLINED = "risk_declined"
    NETWORK_TIMEOUT = "network_timeout"
    CARD_DECLINED = "card_declined"
    UPI_PSP_ERROR = "upi_psp_error"
    UNKNOWN = "unknown"


class RecoveryStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    RECOVERED = "recovered"
    LOST = "lost"
    SKIPPED = "skipped"


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("razorpay_event_id", name="uq_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razorpay_event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Recovery(Base):
    __tablename__ = "recoveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), index=True)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), index=True)
    merchant_customer_id: Mapped[str | None] = mapped_column(String(128), index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    cohort: Mapped[str] = mapped_column(String(32), index=True)
    original_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_error_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=RecoveryStatus.PENDING.value, index=True)
    recovered_amount_paise: Mapped[int] = mapped_column(Integer, default=0)
    strategy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    strategy_mode: Mapped[str] = mapped_column(String(16), default="agent", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    gateway_fee_paise: Mapped[int] = mapped_column(Integer, default=0)
    # Recovery-side reference: for payment-link recoveries this is the link_id;
    # for retry recoveries this is the new order_id. Lets close-loop webhooks
    # (payment_link.paid / payment.captured) map back to the recovery row.
    razorpay_recovery_ref: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    audit: Mapped[list["AuditEntry"]] = relationship(
        back_populates="recovery", cascade="all, delete-orphan", order_by="AuditEntry.created_at"
    )


class AuditEntry(Base):
    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_id: Mapped[int] = mapped_column(ForeignKey("recoveries.id", ondelete="CASCADE"), index=True)
    step: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(32))  # rules | llm | strategist | executor | razorpay
    detail: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    recovery: Mapped[Recovery] = relationship(back_populates="audit")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cohort: Mapped[str] = mapped_column(String(32), unique=True)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    backoff_seconds: Mapped[list] = mapped_column(JSON, default=list)
    preferred_rails: Mapped[list] = mapped_column(JSON, default=list)
    dunning_channels: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)


class LearnedOutcome(Base):
    __tablename__ = "learned_outcomes"
    __table_args__ = (UniqueConstraint("cohort", "action", "hour_ist", name="uq_learned_ckey"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cohort: Mapped[str] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    hour_ist: Mapped[int] = mapped_column(Integer, index=True)
    attempted: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)


class BanditArm(Base):
    """Beta(α, β) posterior for a contextual bandit arm.

    One row per (cohort, ticket_bucket, hour_bucket, action). Thompson sampling
    at decision time draws p ~ Beta(α, β) for each candidate action and picks
    argmax. On outcome we increment α or β. Cold cohorts are bootstrapped from
    hardcoded priors so the first few decisions are still sensible.
    """
    __tablename__ = "bandit_arms"
    __table_args__ = (UniqueConstraint("cohort", "ticket_bucket", "hour_bucket", "action",
                                       name="uq_bandit_arm"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cohort: Mapped[str] = mapped_column(String(32), index=True)
    ticket_bucket: Mapped[str] = mapped_column(String(16), index=True)  # small|mid|large
    hour_bucket: Mapped[str] = mapped_column(String(16), index=True)    # morning|day|evening|night
    action: Mapped[str] = mapped_column(String(32), index=True)
    alpha: Mapped[float] = mapped_column(default=1.0)  # successes + prior
    beta: Mapped[float] = mapped_column(default=1.0)   # failures + prior
    pulls: Mapped[int] = mapped_column(Integer, default=0)


class RecoveryMemory(Base):
    """Semantic memory: per-recovery TF-IDF text + outcome + strategy used.

    On a new failure, retrieve k-nearest past successful recoveries by cosine
    similarity and use the distribution of what worked for them as an
    additional prior. This is RAG-for-actions on the merchant's own history.
    """
    __tablename__ = "recovery_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recovery_id: Mapped[int] = mapped_column(ForeignKey("recoveries.id", ondelete="CASCADE"), index=True)
    cohort: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(String(1024))
    action_taken: Mapped[str] = mapped_column(String(32))
    succeeded: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.database_url.startswith("sqlite"):
            from sqlalchemy import text
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
            # Under high concurrency the async executor issues many writes
            # against a single-writer store; a 10s busy timeout lets SQLite
            # queue them instead of failing fast, at cost of latency tail.
            await conn.execute(text("PRAGMA busy_timeout=10000"))
            await conn.execute(text("PRAGMA cache_size=-20000"))  # 20MB page cache
            await conn.execute(text("PRAGMA mmap_size=134217728"))  # 128MB mmap


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
