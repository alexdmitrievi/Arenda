from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import CommandHandler, ContextTypes, ConversationHandler, MessageHandler, filters

DEPOSIT, RISK_PCT, STOP_PCT = range(3)


async def start_risk_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
        await msg.reply_text("💰 Введите размер депозита ($):")
    else:
        await update.message.reply_text("💰 Введите размер депозита ($):")
    return DEPOSIT


async def get_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        deposit = float(update.message.text.strip().replace(",", "."))
        if deposit <= 0:
            raise ValueError
        context.user_data["calc_deposit"] = deposit
        await update.message.reply_text("📊 Введите процент риска на сделку (%):")
        return RISK_PCT
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число. Пример: 1000")
        return DEPOSIT


async def get_risk_pct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        risk_pct = float(update.message.text.strip().replace(",", ".").replace("%", ""))
        if risk_pct <= 0 or risk_pct > 100:
            raise ValueError
        context.user_data["calc_risk_pct"] = risk_pct
        await update.message.reply_text("🛑 Введите процент стоп-лосса (%):")
        return STOP_PCT
    except ValueError:
        await update.message.reply_text("❌ Введите число от 0 до 100. Пример: 2")
        return RISK_PCT


async def get_stop_pct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        stop_pct = float(update.message.text.strip().replace(",", ".").replace("%", ""))
        if stop_pct <= 0:
            raise ValueError

        deposit = context.user_data.get("calc_deposit", 0)
        risk_pct = context.user_data.get("calc_risk_pct", 0)

        risk_amount = deposit * risk_pct / 100
        position_size = risk_amount / (stop_pct / 100)

        result = (
            f"📊 <b>Результаты расчёта:</b>\n\n"
            f"💰 Депозит: ${deposit:,.2f}\n"
            f"⚠️ Риск на сделку: {risk_pct}%\n"
            f"💸 Сумма риска: ${risk_amount:,.2f}\n"
            f"🛑 Стоп-лосс: {stop_pct}%\n\n"
            f"📏 <b>Рекомендуемый размер позиции: ${position_size:,.2f}</b>\n\n"
            f"При срабатывании стоп-лосса вы потеряете ${risk_amount:,.2f} "
            f"({risk_pct}% от депозита)."
        )

        from app.bot.keyboards.menu import MENU_KEYBOARD
        await update.message.reply_text(result, reply_markup=MENU_KEYBOARD)

        for key in ("calc_deposit", "calc_risk_pct"):
            context.user_data.pop(key, None)

        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите корректное число. Пример: 5")
        return STOP_PCT


async def cancel_calc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from app.bot.keyboards.menu import MENU_KEYBOARD
    await update.message.reply_text("🔙 Калькулятор отменён.", reply_markup=MENU_KEYBOARD)
    return ConversationHandler.END


risk_calc_handler = ConversationHandler(
    entry_points=[CommandHandler("calc", start_risk_calc)],
    states={
        DEPOSIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_deposit)],
        RISK_PCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_risk_pct)],
        STOP_PCT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_stop_pct)],
    },
    fallbacks=[CommandHandler("cancel", cancel_calc)],
)
