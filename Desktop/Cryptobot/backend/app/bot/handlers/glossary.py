from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from app.services.ai.client import get_deepseek_client
from app.config import settings


async def handle_glossary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_text = (msg.text or "").strip()

    if user_text == "↩️ Выйти в меню":
        context.user_data.pop("in_glossary", None)
        from app.bot.keyboards.menu import MENU_KEYBOARD
        await msg.reply_text("🔙 Возвращаемся в меню.", reply_markup=MENU_KEYBOARD)
        return

    if not context.user_data.get("in_glossary"):
        context.user_data["in_glossary"] = True
        await msg.reply_text(
            "📚 Напишите термин, который нужно объяснить.\n"
            "«↩️ Выйти в меню» — для возврата.",
            reply_markup=ReplyKeyboardMarkup([["↩️ Выйти в меню"]], resize_keyboard=True),
        )
        return

    status = await msg.reply_text("🔍 Ищу определение...")

    try:
        client = get_deepseek_client()
        prompt = (
            f"You are a professional trader and educator with 10+ years experience.\n\n"
            f"Explain in simple terms what '{user_text}' means, for a complete beginner.\n"
            "1) Short, clear definition (1-2 sentences).\n"
            "2) Simple analogy (comparing to everyday life).\n"
            "3) Concrete trading example.\n"
            "Avoid jargon. Answer in Russian."
        )

        response = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        text = response.choices[0].message.content.strip()
        await status.edit_text(f"📘 {user_text}:\n\n{text}")

    except Exception as e:
        await status.edit_text("⚠️ Не удалось найти определение. Попробуйте позже.")
