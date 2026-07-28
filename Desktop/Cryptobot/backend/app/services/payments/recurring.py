import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.subscription import (
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.services.payments.yookassa import create_auto_payment, get_plan_price

logger = logging.getLogger("tbx.payments.recurring")


async def process_recurring_payments() -> dict:
    total = 0
    succeeded = 0
    failed = 0

    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=1)

    async with async_session_factory() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.auto_renew == True,
                Subscription.expires_at <= window_end,
                Subscription.yookassa_payment_method_id.isnot(None),
            )
        )
        subscriptions = result.scalars().all()

        for sub in subscriptions:
            total += 1
            try:
                price = get_plan_price(sub.plan)
                if price <= 0:
                    continue

                yk_data = await create_auto_payment(
                    payment_method_id=sub.yookassa_payment_method_id,
                    amount=price,
                    description=f"TBX {sub.plan.value} — авто-продление",
                    plan=sub.plan,
                )

                payment = Payment(
                    user_id=sub.user_id,
                    subscription_id=str(sub.id),
                    yookassa_payment_id=yk_data["id"],
                    amount=price,
                    currency="RUB",
                    vat_rate=4,
                    status=PaymentStatus.PENDING,
                    description=f"Auto-renewal: {sub.plan.value}",
                    plan=sub.plan,
                )
                db.add(payment)
                sub.expires_at = None
                succeeded += 1

            except Exception as e:
                logger.error("Recurring payment failed for sub %s: %s", sub.id, e)
                failed += 1

        await db.commit()

    return {"total": total, "succeeded": succeeded, "failed": failed}
