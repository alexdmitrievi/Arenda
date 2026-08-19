from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID as UUIDType

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class TradeStatus(StrEnum):
    PENDING = "pending"  # DB row written, exchange order not yet confirmed
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class StrategyType(StrEnum):
    SMC = "smc"
    GRID = "grid"
    DCA = "dca"
    TREND = "trend"


class Trade(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "trades"

    user_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[TradeSide] = mapped_column(
        Enum(TradeSide, name="trade_side"), nullable=False
    )
    strategy_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=True
    )
    signal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("signals.id"), nullable=True
    )
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    size: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    status: Mapped[TradeStatus] = mapped_column(
        Enum(TradeStatus, name="trade_status"), default=TradeStatus.OPEN
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Position(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "positions"

    user_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide, name="trade_side"), nullable=False)
    size: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    avg_entry: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    unrealized_pnl_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)


class Signal(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "signals"

    strategy_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("strategies.id"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[TradeSide] = mapped_column(
        Enum(TradeSide, name="trade_side"), nullable=False
    )
    entry: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    take_profit: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[int] = mapped_column(default=50)
    metadata_: Mapped[dict | None] = mapped_column("signal_metadata", JSONB, nullable=True)
    executed: Mapped[bool] = mapped_column(default=False)


class Strategy(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "strategies"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[StrategyType] = mapped_column(
        Enum(StrategyType, name="strategy_type"), nullable=False
    )
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(default=False)
    user_id: Mapped[UUIDType | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
