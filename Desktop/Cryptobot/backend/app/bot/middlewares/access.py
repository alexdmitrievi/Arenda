from telegram import Update
from telegram.ext import ContextTypes

from app.api.deps import get_db
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User


async def subscription_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user is None:
        return

    allowed_callbacks = {
        "start_menu", "back_to_menu", "back_to_signal", "back_to_strategy",
        "get_email", "interpret_calendar", "ref_bybit", "ref_forex4you",
        "market_crypto", "market_forex", "screenshot_help",
        "prop_firm_info", "trial_start",
    }

    if update.callback_query:
        cb_data = update.callback_query.data or ""
        if any(cb_data.startswith(prefix) for prefix in allowed_callbacks):
            return

    free_texts = {"💰 Купить", "ℹ️ О боте", "🔗 Бесплатный доступ", "💸 Криптообмен", "↩️ Выйти в меню", "↩️ Вернуться в меню"}

    if update.message and update.message.text:
        if update.message.text in free_texts:
            return

    from app.core.database import async_session_factory
    from sqlalchemy import select

    async with async_session_factory() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == str(user.id),
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
            )
        )
        sub = result.scalar_one_or_none()

        if sub is None:
            if update.message:
                await update.message.reply_text(
                    "🔒 Доступ только по подписке.\n"
                    "Нажмите «💰 Купить» для активации или «🆓 7 дней бесплатно».",
                )
            elif update.callback_query:
                await update.callback_query.answer("Требуется подписка", show_alert=True)
            raise ValueError("subscription_required")
