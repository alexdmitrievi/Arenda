import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionStatus
from app.bot.keyboards.menu import MENU_KEYBOARD
from app.bot.utils.formatting import MONTHLY_PRICE_USD, LIFETIME_PRICE_USD

logger = logging.getLogger("tbx.bot.payments")


async def handle_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user

    async with async_session_factory() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == str(user.id),
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
            )
        )
        if result.scalar_one_or_none():
            await msg.reply_text("✅ У вас уже активирована подписка!", reply_markup=MENU_KEYBOARD)
            return

    text = (
        "💳 <b>TBX Trade Terminal — тарифы:</b>\n\n"
        f"🟢 <b>Trader</b> — 4 900 ₽/мес (с НДС)\n"
        "• Все стратегии, автоследование, 3 биржи\n\n"
        f"🔵 <b>Investor Pro</b> — 9 900 ₽/мес (с НДС)\n"
        "• + DCA портфели, ребалансировка, отчёты\n\n"
        f"🟣 <b>Prop Firm Master</b> — 14 900 ₽/мес (с НДС)\n"
        "• + Пропп-челленджи, комьюнити\n\n"
        "🆓 <b>7 дней бесплатно</b> — попробуйте всё!\n\n"
        "Для оплаты перейдите в веб-приложение или напишите @zhbankov_alex\n"
        "Для юрлиц — выставим счёт с НДС."
    )
    await msg.reply_text(text, reply_markup=MENU_KEYBOARD)


async def handle_trial_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    async with async_session_factory() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == str(user.id),
                Subscription.trial_used == True,
            )
        )
        if result.scalar_one_or_none():
            await query.edit_message_text("❌ Вы уже использовали пробный период.")
            return

        trial = Subscription(
            user_id=str(user.id),
            plan=SubscriptionPlan.TRADER,
            status=SubscriptionStatus.TRIAL,
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + __import__("datetime").timedelta(days=7),
            trial_used=True,
        )
        db.add(trial)
        await db.commit()

    await query.edit_message_text(
        "🎉 Пробный период активирован!\n"
        "У вас 7 дней полного доступа ко всем функциям.\n"
        "Выберите действие в меню 👇",
    )


async def handle_free_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.bot.keyboards.inline import broker_ref_keyboard

    await update.message.reply_text(
        "🔗 Бесплатный доступ через брокера:\n\n"
        "1. Зарегистрируйтесь по реферальной ссылке\n"
        "2. Внесите мин. депозит (Bybit: $150, Forex4You: $200)\n"
        "3. Пришлите ваш UID в этот чат\n\n"
        "После проверки — доступ будет активирован.",
        reply_markup=broker_ref_keyboard(),
    )


async def handle_uid_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import re
    msg = update.effective_message
    raw = (msg.text or "").strip()

    digits = re.sub(r"\D", "", raw)
    if len(digits) < 5:
        await msg.reply_text("❗️ Пришлите UID цифрами. Пример: 24676081.", reply_markup=MENU_KEYBOARD)
        return

    context.user_data.pop("awaiting_uid", None)

    async with async_session_factory() as db:
        result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == str(update.effective_user.id),
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        if not result.scalar_one_or_none():
            sub = Subscription(
                user_id=str(update.effective_user.id),
                plan=SubscriptionPlan.TRADER,
                status=SubscriptionStatus.ACTIVE,
                started_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + __import__("datetime").timedelta(days=30),
            )
            db.add(sub)
            await db.commit()

    await msg.reply_text(
        f"✅ UID {digits} принят. Доступ активирован на 30 дней.\n"
        "После проверки брокером — продлим навсегда.",
        reply_markup=MENU_KEYBOARD,
    )
