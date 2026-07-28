from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from app.services.ai.client import get_deepseek_client
from app.config import settings

PSYCHOLOGIST_PROMPT = (
    "You are a GPT-psychologist for traders. "
    "You respond with warm irony and light humor, helping traders cope with losses. "
    "Avoid gender-specific words. Use neutral terms: friend, colleague, trader.\n\n"
    "Follow this structure:\n"
    "1️⃣ Empathetic reaction.\n"
    "2️⃣ Metaphor (drawdown isn't the end).\n"
    "3️⃣ Fact about famous traders' losing streaks.\n"
    "4️⃣ One micro-action to feel in control.\n"
    "5️⃣ Trading meme or funny quote.\n\n"
    "Answer in Russian. Be specific, warm, slightly ironic."
)


async def handle_psychologist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_text = msg.text.strip() if msg.text else ""

    if user_text == "↩️ Выйти в меню":
        context.user_data.pop("in_therapy", None)
        from app.bot.keyboards.menu import MENU_KEYBOARD
        await msg.reply_text("🔙 Возвращаемся в меню.", reply_markup=MENU_KEYBOARD)
        return

    if not context.user_data.get("in_therapy"):
        context.user_data["in_therapy"] = True
        await msg.reply_text(
            "😵‍💫 Рынок опять побрил? Бывает.\n\n"
            "Напиши, что случилось — выслушаю, подбодрю и вставлю мем.\n"
            "«↩️ Выйти в меню» — когда захочешь вернуться.",
            reply_markup=ReplyKeyboardMarkup([["↩️ Выйти в меню"]], resize_keyboard=True),
        )
        return

    status = await msg.reply_text("🧘 Думаю...")

    try:
        client = get_deepseek_client()
        response = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": PSYCHOLOGIST_PROMPT},
                {"role": "user", "content": f"User's message:\n{user_text}"},
            ],
            temperature=0.7,
        )

        text = response.choices[0].message.content.strip()
        await status.edit_text(f"🧘 GPT-психолог:\n\n{text}")

    except Exception as e:
        await status.edit_text("⚠️ Психолог временно недоступен. Попробуйте позже.")
