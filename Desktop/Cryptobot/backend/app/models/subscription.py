from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID as UUIDType

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class SubscriptionPlan(StrEnum):
    DEMO = "demo"
    TRADER = "trader"
    INVESTOR_PRO = "investor_pro"
    PROP_FIRM_MASTER = "prop_firm_master"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    PENDING = "pending"
    TRIAL = "trial"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    REFUNDED = "refunded"


PLAN_PRICES_USD: dict[SubscriptionPlan, Decimal] = {
    SubscriptionPlan.DEMO: Decimal("0"),
    SubscriptionPlan.TRADER: Decimal("29.00"),
    SubscriptionPlan.INVESTOR_PRO: Decimal("79.00"),
    SubscriptionPlan.PROP_FIRM_MASTER: Decimal("149.00"),
    SubscriptionPlan.ENTERPRISE: Decimal("0"),
}

# Fixed RUB prices — never derived from a live FX rate so charges stay predictable.
PLAN_PRICES_RUB: dict[SubscriptionPlan, Decimal] = {
    SubscriptionPlan.DEMO: Decimal("0"),
    SubscriptionPlan.TRADER: Decimal("2900.00"),
    SubscriptionPlan.INVESTOR_PRO: Decimal("7900.00"),
    SubscriptionPlan.PROP_FIRM_MASTER: Decimal("14900.00"),
    SubscriptionPlan.ENTERPRISE: Decimal("0"),
}

# CryptoCloud charges in USDT ≈ USD
PLAN_PRICES = PLAN_PRICES_USD

PLAN_FEATURES: dict[SubscriptionPlan, list[str]] = {
    SubscriptionPlan.DEMO: [
        "Задержка данных 15 мин",
        "1 стратегия",
        "1 портфель",
        "Без автоисполнения",
    ],
    SubscriptionPlan.TRADER: [
        "Все стратегии",
        "Автоследование",
        "Риск-менеджер",
        "До 3 бирж",
        "Telegram сигналы",
    ],
    SubscriptionPlan.INVESTOR_PRO: [
        "Всё из Trader",
        "DCA портфели",
        "Ребалансировка",
        "Налоговый отчёт",
        "Приоритетная поддержка",
    ],
    SubscriptionPlan.PROP_FIRM_MASTER: [
        "Всё из Investor Pro",
        "Помощь с пропп-челленджами",
        "Оптимизатор стратегий",
        "Трекер прогресса",
        "Закрытое комьюнити",
    ],
    SubscriptionPlan.ENTERPRISE: [
        "Всё из Prop Firm Master",
        "White-label",
        "API доступ",
        "Выделенный сервер",
        "Персональный менеджер",
    ],
}


class Subscription(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    user_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(SubscriptionPlan, name="subscription_plan"),
        default=SubscriptionPlan.DEMO,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status"),
        default=SubscriptionStatus.PENDING,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False)
    yookassa_payment_method_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    trial_used: Mapped[bool] = mapped_column(Boolean, default=False)


class Payment(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "payments"

    user_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    subscription_id: Mapped[UUIDType | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True
    )
    yookassa_payment_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    vat_rate: Mapped[int] = mapped_column(default=4)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"), default=PaymentStatus.PENDING
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[SubscriptionPlan | None] = mapped_column(
        Enum(SubscriptionPlan, name="subscription_plan"), nullable=True
    )
    metadata_: Mapped[dict | None] = mapped_column(
        "metadata_json", JSONB, nullable=True
    )


class Invoice(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "invoices"

    user_id: Mapped[UUIDType] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    payment_id: Mapped[UUIDType | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    invoice_number: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_inn: Mapped[str] = mapped_column(String(12), nullable=False)
    company_kpp: Mapped[str | None] = mapped_column(String(9), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    vat_rate: Mapped[int] = mapped_column(default=4)
    vat_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft")
