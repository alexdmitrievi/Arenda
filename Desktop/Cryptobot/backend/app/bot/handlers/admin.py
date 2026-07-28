from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select, func

from app.core.database import async_session_factory
from app.models.subscription import Subscription, SubscriptionStatus, Payment
from app.models.user import User, UserRole
from app.config import settings
from app.bot.keyboards.menu import MENU_KEYBOARD


async def admin_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in settings.ADMIN_IDS:
        await update.message.reply_text("⛔ Нет прав.")
        return

    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Использование: /grant <user_id>")
        return

    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом.")
        return

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.telegram_id == target_id))
        target = result.scalar_one_or_none()

        if not target:
            target = User(telegram_id=target_id, username=args[1] if len(args) > 1 else None)
            db.add(target)
            await db.flush()

        sub_result = await db.execute(
            select(Subscription).where(
                Subscription.user_id == str(target.id),
                Subscription.status == SubscriptionStatus.ACTIVE,
            )
        )
        if sub_result.scalar_one_or_none():
            await update.message.reply_text(f"✅ Пользователь {target_id} уже имеет доступ.")
            return

        from datetime import datetime, timedelta, timezone
        sub = Subscription(
            user_id=str(target.id),
            plan=SubscriptionPlan.TRADER,
            status=SubscriptionStatus.ACTIVE,
            started_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        db.add(sub)
        await db.commit()

    await update.message.reply_text(f"✅ Доступ выдан пользователю {target_id} на 365 дней.")


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in settings.ADMIN_IDS:
        return

    async with async_session_factory() as db:
        total = await db.execute(select(func.count(User.id)))
        active_subs = await db.execute(
            select(func.count(Subscription.id)).where(
                Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL])
            )
        )

        total_count = total.scalar() or 0
        active_count = active_subs.scalar() or 0

    await update.message.reply_text(
        f"📊 Статистика:\n"
        f"👥 Всего пользователей: {total_count}\n"
        f"✅ Активных подписок: {active_count}\n"
    )


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in settings.ADMIN_IDS:
        return

    text = " ".join(context.args or [])
    if not text:
        await update.message.reply_text("Использование: /broadcast <текст>")
        return

    async with async_session_factory() as db:
        result = await db.execute(
            select(User).where(User.telegram_id.isnot(None))
        )
        users = result.scalars().all()

    sent = 0
    for u in users:
        if u.telegram_id:
            try:
                await context.bot.send_message(chat_id=u.telegram_id, text=text)
                sent += 1
            except Exception:
                pass

    await update.message.reply_text(f"📢 Рассылка отправлена: {sent}/{len(users)} пользователей.")


async def admin_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in settings.ADMIN_IDS:
        return
    await update.message.reply_text("♻️ Reload command received. (DB-based, no cache reload needed.)")
