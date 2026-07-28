from telegram import ReplyKeyboardMarkup, KeyboardButton

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 Трейдер"), KeyboardButton("💡 Инвестор")],
        [KeyboardButton("🔍 Новости"), KeyboardButton("📚 Термин")],
        [KeyboardButton("🌱 Психолог"), KeyboardButton("🎯 Калькулятор")],
        [KeyboardButton("💰 Купить"), KeyboardButton("ℹ️ О боте")],
        [KeyboardButton("🔗 Бесплатный доступ"), KeyboardButton("🏆 Пропп-компании")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Выберите действие...",
)

BACK_MENU = ReplyKeyboardMarkup(
    [["↩️ Выйти в меню"]],
    resize_keyboard=True,
)

ADMIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🚀 Трейдер"), KeyboardButton("💡 Инвестор")],
        [KeyboardButton("🔍 Новости"), KeyboardButton("📚 Термин")],
        [KeyboardButton("🌱 Психолог"), KeyboardButton("🎯 Калькулятор")],
        [KeyboardButton("💰 Купить"), KeyboardButton("ℹ️ О боте")],
        [KeyboardButton("🔗 Бесплатный доступ"), KeyboardButton("🏆 Пропп-компании")],
        [KeyboardButton("📌 Сетап"), KeyboardButton("📊 Статистика")],
    ],
    resize_keyboard=True,
    input_field_placeholder="Админ-меню...",
)
