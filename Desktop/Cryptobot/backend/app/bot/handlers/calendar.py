import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.utils.images import extract_image_bytes, to_jpeg_base64
from app.services.ai.client import get_deepseek_client
from app.config import settings

logger = logging.getLogger("tbx.bot.calendar")

NEWS_PROMPT = (
    "You are a macro analyst. Interpret an economic calendar screenshot (CPI, PPI, NFP, ISM, etc.). "
    "Your single mission: tie this event to the upcoming FOMC meeting (rate CUT or HOLD, no HIKE).\n\n"
    "Hard constraints:\n"
    "- Education-only. No investment advice. No trading signals.\n"
    "- OUTPUT: RUSSIAN ONLY.\n"
    "- Be concrete. Avoid buzzwords.\n\n"
    "Structure:\n"
    "1) Событие и цифры: название, факт / прогноз / пред.\n"
    "2) Суть данных: сильнее/слабее прогноза и что это значит для ставки ФРС\n"
    "3) Связь с FOMC: шансы снижения/сохранения, риторика\n"
    "4) Влияние на рынки (1-3 дня): DXY, UST, SPX/Nasdaq\n"
    "5) Крипто и альтсезон\n"
    "6) Сценарии (bull/bear)\n"
    "7) Риски и что смотреть дальше"
)


async def handle_calendar_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    status = await msg.reply_text("🔎 Читаю календарь, оцениваю влияние на ФРС...")

    try:
        image_bytes = await extract_image_bytes(update, context)
        if not image_bytes:
            await status.edit_text("❌ Не вижу скрина календаря. Пришлите PNG/JPG с полями: событие, Факт/Прогноз/Пред.")
            return

        img_b64 = to_jpeg_base64(image_bytes)
        client = get_deepseek_client()

        response = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": NEWS_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": "Интерпретируй этот экономический календарь."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}
            ],
            temperature=0.2,
        )

        analysis = (response.choices[0].message.content or "").strip()
        if not analysis:
            analysis = "Не удалось распознать данные календаря. Пришлите более чёткий скрин."

        if len(analysis) > 4000:
            chunks = [analysis[i:i+3800] for i in range(0, len(analysis), 3800)]
            await status.edit_text(f"🧠 Макро-интерпретация:\n\n{chunks[0]}")
            for chunk in chunks[1:]:
                await msg.reply_text(chunk)
        else:
            await status.edit_text(f"🧠 Макро-интерпретация:\n\n{analysis}")

    except Exception as e:
        logger.exception("Calendar analysis failed")
        await status.edit_text("❌ Не удалось интерпретировать календарь. Попробуйте другой скрин.")
