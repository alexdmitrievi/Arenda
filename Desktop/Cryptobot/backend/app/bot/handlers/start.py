from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.bot.keyboards.menu import ADMIN_MENU, MENU_KEYBOARD
from app.config import settings


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id if user else None
    is_admin = user_id in settings.ADMIN_IDS

    welcome = (
        "🤖 <b>TBX Trade Terminal</b>\n\n"
        "Ваш AI-ассистент для трейдинга и инвестиций.\n\n"
        "Что я умею:\n"
        "• 🚀 SMC-анализ графика за 10 секунд\n"
        "• 💡 Инвестиционные DCA-планы\n"
        "• 🔍 Макро-интерпретация новостей\n"
        "• 🌱 Психолог для трейдера\n"
        "• 🎯 Калькулятор риска\n"
        "• 🏆 Помощь с пропп-челленджами\n\n"
        "Выберите действие в меню 👇"
    )

    keyboard = ADMIN_MENU if is_admin else MENU_KEYBOARD
    await update.message.reply_text(welcome, reply_markup=keyboard)


async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 <b>TBX Trade Terminal</b> — AI-ассистент для крипты и форекса.\n\n"
        "Что умеет:\n"
        "• По скрину графика за 10 сек: Entry / Stop / TakeProfit\n"
        "• Инвест-план: покупка, уровни DCA, цели и риски\n"
        "• Макро-интерпретация новостей (календарь, CPI, ФРС)\n"
        "• Обучение простым языком и словарь терминов\n"
        "• Психолог для трейдера и калькулятор риска\n"
        "• Помощь с пропп-компаниями (Hashhadge, FTMO)\n\n"
        "📌 Важно: информация носит образовательный характер\n"
        "и не является инвестиционной рекомендацией."
    )
    await update.message.reply_text(text)


def setup_start_handlers():
    return [
        CommandHandler("start", start_handler),
        CommandHandler("help", about_handler),
    ]
