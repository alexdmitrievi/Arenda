from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class PortfolioType(StrEnum):
    CONSERVATIVE = "conservative"
    DEFI = "defi"
    AGGRESSIVE = "aggressive"
    CUSTOM = "custom"


class RebalanceFrequency(StrEnum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    MANUAL = "manual"


class DCAFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ChallengeStatus(StrEnum):
    ACTIVE = "active"
    PASSED = "passed"
    FAILED = "failed"
    PAUSED = "paused"


class Portfolio(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "portfolios"

    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[PortfolioType] = mapped_column(Enum(PortfolioType, name="portfolio_type"), default=PortfolioType.CUSTOM)
    allocation: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rebalance_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("5.00"))
    rebalance_frequency: Mapped[RebalanceFrequency] = mapped_column(
        Enum(RebalanceFrequency, name="rebalance_frequency"), default=RebalanceFrequency.MANUAL
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class DCAPlan(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "dca_plans"

    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    portfolio_id: Mapped[UUIDType | None] = mapped_column(UUID(as_uuid=True), ForeignKey("portfolios.id"), nullable=True)
    asset: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_per_period: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    frequency: Mapped[DCAFrequency] = mapped_column(Enum(DCAFrequency, name="dca_frequency"), default=DCAFrequency.WEEKLY)
    atr_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2.00"))
    active_steps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    next_execution_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class PropFirmChallenge(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "prop_firm_challenges"

    user_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    firm: Mapped[str] = mapped_column(String(64), nullable=False)
    account_size: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[ChallengeStatus] = mapped_column(
        Enum(ChallengeStatus, name="challenge_status"), default=ChallengeStatus.ACTIVE
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


PORTFOLIO_TEMPLATES = {
    PortfolioType.CONSERVATIVE: {
        "name": "Conservative",
        "allocation": {"BTC": 40, "ETH": 20, "USDT": 40},
        "description": "Низкий риск. Биткоин + стейблкоин для сохранения капитала.",
    },
    PortfolioType.DEFI: {
        "name": "DeFi Index",
        "allocation": {"UNI": 20, "AAVE": 20, "MKR": 15, "LDO": 15, "CRV": 10, "ETH": 20},
        "description": "Средний риск. Индекс токенов DeFi-протоколов.",
    },
    PortfolioType.AGGRESSIVE: {
        "name": "Aggressive Growth",
        "allocation": {"BTC": 30, "ETH": 30, "SOL": 20, "ARB": 10, "OP": 10},
        "description": "Высокий риск. Акцент на L1/L2 активы с потенциалом роста.",
    },
}
