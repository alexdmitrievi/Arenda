import logging

from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import settings
from app.bot.handlers.start import setup_start_handlers, start_handler
from app.bot.handlers.trading import handle_trader_market_selection, handle_trader_photo
from app.bot.handlers.investor import handle_investor_photo
from app.bot.handlers.calendar import handle_calendar_photo
from app.bot.handlers.calculator import risk_calc_handler, start_risk_calc
from app.bot.handlers.psychologist import handle_psychologist
from app.bot.handlers.glossary import handle_glossary
from app.bot.handlers.payments import handle_buy, handle_trial_start, handle_free_access, handle_uid_submission
from app.bot.handlers.admin import admin_grant, admin_stats, admin_broadcast, admin_reload
from app.bot.handlers.prop_firm import handle_prop_firm_menu
from app.bot.handlers.signals import signals_command, latest_signal_command

logger = logging.getLogger("tbx.bot")

_application = None


async def build_bot():
    global _application
    if _application is not None:
        return _application

    builder = ApplicationBuilder().token(settings.TELEGRAM_TOKEN)

    _application = builder.build()

    for handler in setup_start_handlers():
        _application.add_handler(handler)

    _application.add_handler(CommandHandler("grant", admin_grant))
    _application.add_handler(CommandHandler("stats", admin_stats))
    _application.add_handler(CommandHandler("broadcast", admin_broadcast))
    _application.add_handler(CommandHandler("reload", admin_reload))

    _application.add_handler(CommandHandler("signals", signals_command))
    _application.add_handler(CommandHandler("signal", latest_signal_command))

    _application.add_handler(risk_calc_handler)

    _application.add_handler(CallbackQueryHandler(
        handle_trader_market_selection, pattern="^market_(crypto|forex)$"
    ))
    _application.add_handler(CallbackQueryHandler(
        handle_trial_start, pattern="^trial_start$"
    ))
    _application.add_handler(CallbackQueryHandler(
        start_risk_calc, pattern="^start_risk_calc$"
    ))
    _application.add_handler(CallbackQueryHandler(
        handle_prop_firm_menu, pattern="^prop_firm_"
    ))

    _application.add_handler(MessageHandler(
        filters.PHOTO | filters.Document.IMAGE, handle_trader_photo
    ))

    _application.add_handler(MessageHandler(
        filters.Regex(r"^🚀 Трейдер$"), lambda u, c: u.message.reply_text(
            "📈 Пришлите скриншот графика (4H/1H) с индикаторами SMC.\n"
            "Видны: BOS, CHoCH, уровни, FVG."
        )
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^💡 Инвестор$"), lambda u, c: u.message.reply_text(
            "💡 Пришлите скриншот графика для DCA-плана.\n"
            "Инструмент: SPOT, LONG only, без плеча."
        )
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^🔍 Новости$"), lambda u, c: u.message.reply_text(
            "📸 Пришлите скриншот экономического календаря.\n"
            "Я распознаю событие и дам интерпретацию."
        )
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^📚 Термин$"), handle_glossary
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^🌱 Психолог$"), handle_psychologist
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^🎯 Калькулятор$"), start_risk_calc
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^💰 Купить$"), handle_buy
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^ℹ️ О боте$"), lambda u, c: u.message.reply_text(
            "🤖 TBX Trade Terminal — AI-ассистент для трейдинга и инвестиций.\n\n"
            "• SMC-анализ графиков\n• DCA-планы\n• Макро-интерпретация\n"
            "• Психолог\n• Пропп-челленджи\n\n"
            "Важно: информация образовательная, не является инвестиционной рекомендацией."
        )
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^🔗 Бесплатный доступ$"), handle_free_access
    ))
    _application.add_handler(MessageHandler(
        filters.Regex(r"^🏆 Пропп-компании$"), handle_prop_firm_menu
    ))

    _application.add_handler(MessageHandler(
        filters.Regex(r"^↩️ (Выйти в меню|Вернуться в меню)$"),
        lambda u, c: u.message.reply_text("🔙 Главное меню.", reply_markup=None)
    ))

    logger.info("Bot handlers registered")
    return _application


async def start_bot():
    app = await build_bot()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message", "callback_query"])
    logger.info("Telegram Bot polling started")


async def stop_bot():
    global _application
    if _application is not None:
        await _application.updater.stop()
        await _application.stop()
        await _application.shutdown()
        _application = None
        logger.info("Telegram Bot stopped")


async def send_message_safe(telegram_id: int | str, text: str, parse_mode: str | None = None) -> bool:
    """Send a message if the bot is running; never raises (blocked users, bot off, etc.)."""
    if _application is None:
        return False
    try:
        await _application.bot.send_message(chat_id=telegram_id, text=text, parse_mode=parse_mode)
        return True
    except Exception as e:
        logger.warning("Failed to send message to %s: %s", telegram_id, e)
        return False
