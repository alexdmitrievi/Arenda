import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, desc
from telegram import Update
from telegram.ext import ContextTypes

from app.core.database import async_session_factory
from app.models.trade import Signal

logger = logging.getLogger("tbx.bot.trading")


def _format_signal_message(signal: Signal) -> str:
    direction_emoji = "🟢 LONG" if str(signal.direction) == "buy" else "🔴 SHORT"
    entry = float(signal.entry)
    sl = float(signal.stop_loss)
    tp_list = signal.take_profit if isinstance(signal.take_profit, list) else []

    msg = f"{direction_emoji}\n"
    msg += f"📊 {signal.symbol}\n\n"
    msg += f"🎯 Вход: ${entry:,.2f}\n"
    msg += f"🛑 Стоп: ${sl:,.2f}\n"

    for i, tp in enumerate(tp_list[:3], 1):
        msg += f"💰 TP{i}: ${tp:,.2f}\n"

    risk = abs(entry - sl)
    if risk > 0 and tp_list:
        reward = abs(tp_list[0] - entry)
        rr = reward / risk if risk > 0 else 0
        msg += f"\n📐 R:R = 1:{rr:.1f}\n"

    msg += f"🎲 Уверенность: {signal.confidence}%\n"
    msg += f"⏰ {signal.created_at.strftime('%d.%m.%Y %H:%M UTC') if signal.created_at else ''}"

    return msg


async def signals_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session_factory() as db:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await db.execute(
            select(Signal)
            .where(Signal.created_at >= since, Signal.confidence >= 50)
            .order_by(desc(Signal.created_at))
            .limit(10)
        )
        signals = result.scalars().all()

    if not signals:
        await update.message.reply_text("📭 Нет активных сигналов за последние 24 часа.")
        return

    await update.message.reply_text(f"📡 Сигналы за 24 часа: {len(signals)} шт.\n")

    for signal in signals[:5]:
        msg = _format_signal_message(signal)
        await update.message.reply_text(msg)


async def latest_signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with async_session_factory() as db:
        result = await db.execute(
            select(Signal)
            .where(Signal.confidence >= 50)
            .order_by(desc(Signal.created_at))
            .limit(1)
        )
        signal = result.scalar_one_or_none()

    if not signal:
        await update.message.reply_text("📭 Нет сигналов.")
        return

    msg = _format_signal_message(signal)
    await update.message.reply_text(msg)
