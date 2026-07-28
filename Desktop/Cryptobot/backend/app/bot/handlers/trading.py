from telegram import Update
from telegram.ext import ContextTypes

from app.bot.keyboards.inline import market_select_keyboard
from app.bot.utils.images import extract_image_bytes, to_jpeg_base64
from app.bot.utils.formatting import safe_float, round2, calc_rr, fmt_price, fmt_pct, parse_entry_stop_tp
from app.services.ai.client import get_deepseek_client
from app.config import settings

TRADER_PROMPT = (
    "You are a professional SMC (Smart Money Concepts) trader with 20+ years experience in {market} markets. "
    "You master BOS, CHoCH, liquidity grabs, imbalance zones, OTE, premium/discount levels.\n\n"
    "The chart includes only:\n"
    "- LuxAlgo SMC\n"
    "- Support & Resistance Levels\n\n"
    "🎯 Your task: create a swing trade plan with pending orders (limit or stop).\n"
    "Risk/Reward ratio must be at least 1:3.\n\n"
    "✅ Format:\n"
    "1️⃣ Observations — each bullet starts with 🔹\n"
    "2️⃣ Trade Plan:\n🎯 Entry: $...\n🚨 StopLoss: $...\n💰 TakeProfit: $...\n"
    "3️⃣ Risk Note\n4️⃣ Bias: BUY or SELL\n"
    "✅ End with 2-line Russian summary\n\n"
    "🚫 Rules: Answer in Russian, no markdown, no refusal, no apologies"
)


async def handle_trader_market_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    market = query.data.replace("market_", "")
    context.user_data["selected_market"] = market

    await query.edit_message_text(
        f"📈 Рынок: {'Крипто' if market == 'crypto' else 'Forex'}\n"
        "Пришлите скриншот графика (4H или 1H) с индикаторами:\n"
        "• LuxAlgo SMC\n"
        "• Support & Resistance Levels\n\n"
        "На скрине должно быть видно: BOS, CHoCH, уровни, FVG."
    )


async def handle_trader_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    market = context.user_data.get("selected_market", "crypto")
    market_name = "crypto" if market == "crypto" else "forex"

    status_msg = await msg.reply_text("🔍 Анализирую график через SMC-модель...")

    try:
        image_bytes = await extract_image_bytes(update, context)
        if not image_bytes:
            await status_msg.edit_text("❌ Не вижу изображения. Пришлите скрин как фото или файл (PNG/JPG).")
            return

        img_b64 = to_jpeg_base64(image_bytes)
        client = get_deepseek_client()

        prompt = TRADER_PROMPT.format(market=market_name)

        response = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Analyze this chart and provide a trade plan."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}
            ],
            temperature=0.3,
        )

        analysis = response.choices[0].message.content or ""

        entry, stop, tp = parse_entry_stop_tp(analysis)

        risk_line = ""
        if entry and stop and entry != 0:
            risk_abs = abs(entry - stop)
            risk_pct = abs((entry - stop) / entry * 100)
            risk_line = f"\n📌 Область риска ≈ ${risk_abs:.2f} ({risk_pct:.2f}%)"

        rr_line = ""
        if entry and stop and tp and entry != stop:
            rr = calc_rr(entry, stop, tp)
            if rr:
                rr_line = f"\n📊 R:R ≈ 1:{rr:.1f}"
                if rr < 3:
                    rr_line += "\n⚠️ R:R ниже 1:3 — повышенный риск"

        await status_msg.edit_text(
            f"📉 SMC-анализ ({market_name.upper()}):\n\n{analysis}{risk_line}{rr_line}"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка анализа: {str(e)[:200]}")
