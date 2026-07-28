from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def market_select_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Crypto", callback_data="market_crypto")],
        [InlineKeyboardButton("💱 Forex", callback_data="market_forex")],
    ])


def strategy_format_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Скриншот", callback_data="strategy_photo")],
        [InlineKeyboardButton("✍️ Текст", callback_data="strategy_text")],
    ])


def payment_plan_keyboard(monthly_url: str, lifetime_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 4 900 ₽/мес", url=monthly_url)],
        [InlineKeyboardButton("💳 14 900 ₽/мес (Pro)", url=lifetime_url)],
        [InlineKeyboardButton("🆓 7 дней бесплатно", callback_data="trial_start")],
    ])


def risk_calc_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📏 Рассчитать риск", callback_data="start_risk_calc")],
    ])


def broker_ref_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Bybit — регистрация", callback_data="ref_bybit")],
        [InlineKeyboardButton("Forex4You — регистрация", callback_data="ref_forex4you")],
    ])


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("↩️ В меню", callback_data="back_to_menu")],
    ])


def prop_firm_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Начать челлендж", callback_data="prop_firm_start")],
        [InlineKeyboardButton("📊 Мой прогресс", callback_data="prop_firm_progress")],
        [InlineKeyboardButton("ℹ️ Как это работает", callback_data="prop_firm_info")],
    ])
