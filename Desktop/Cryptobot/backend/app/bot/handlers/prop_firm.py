from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards.inline import prop_firm_menu_keyboard
from app.bot.keyboards.menu import MENU_KEYBOARD


PROP_FIRM_INFO = (
    "🏆 <b>Помощь с пропп-компаниями</b>\n\n"
    "Торгуйте не своими деньгами, а капиталом пропп-фирмы!\n\n"
    "<b>Как это работает:</b>\n"
    "1. Покупаете челлендж у пропп-компании ($50-$500)\n"
    "2. Проходите тест: достигаете профит-таргет без нарушения правил\n"
    "3. Получаете funded-аккаунт с реальным капиталом ($10k-$200k)\n"
    "4. Торгуете на деньги фирмы, прибыль делится (обычно 80/20)\n\n"
    "<b>Что даёт TBX:</b>\n"
    "• Стратегии, оптимизированные под правила челленджа\n"
    "• Автостоп при приближении к дневному лимиту потерь\n"
    "• Трекер прогресса: сколько % пройдено, сколько дней осталось\n"
    "• Автоотключение перед high-impact новостями\n\n"
    "<b>Поддерживаемые фирмы:</b>\n"
    "• Hashhadge.com\n"
    "• FTMO\n"
    "• The Funded Trader\n\n"
    "🎯 Тариф Prop Firm Master включает полный доступ."
)


async def handle_prop_firm_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        action = update.callback_query.data

        if action == "prop_firm_start":
            await update.callback_query.edit_message_text(
                "🎯 Для старта челленджа:\n"
                "1. Приобретите челлендж на сайте пропп-компании\n"
                "2. Подключите API-ключи в личном кабинете TBX\n"
                "3. Нажмите «Начать челлендж» в веб-приложении\n\n"
                "Функция будет доступна в веб-версии после обновления.",
                reply_markup=prop_firm_menu_keyboard(),
            )
        elif action == "prop_firm_progress":
            await update.callback_query.edit_message_text(
                "📊 Для отслеживания прогресса откройте веб-приложение TBX.\n"
                "Там вы увидите: % пройдено, дни, текущую просадку, статус правил.",
                reply_markup=prop_firm_menu_keyboard(),
            )
        elif action == "prop_firm_info":
            await update.callback_query.edit_message_text(
                PROP_FIRM_INFO,
                reply_markup=prop_firm_menu_keyboard(),
            )
    else:
        await update.message.reply_text(PROP_FIRM_INFO, reply_markup=prop_firm_menu_keyboard())
