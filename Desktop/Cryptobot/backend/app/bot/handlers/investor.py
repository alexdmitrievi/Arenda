import json
import re
import logging

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.utils.images import extract_image_bytes, to_jpeg_base64
from app.bot.utils.formatting import safe_float, round2, fmt_price, fmt_pct
from app.services.ai.client import get_deepseek_client
from app.config import settings

logger = logging.getLogger("tbx.bot.investor")

INVESTOR_PROMPT = (
    "You are an institutional investor creating a SPOT DCA plan (LONG only). "
    "Always respond with a VALID ONE-LINE JSON as the FIRST line using the schema: "
    '{"direction":"LONG","entry":number|null,"avg_entry":number|null,"stop":number|null,'
    '"tp":[numbers],"dca":[{"price":number,"alloc_pct":number}],"notes":["text"]}. '
    "Prefer providing 4-5 DCA steps with decreasing prices. "
    "Then provide a Russian explanation for a beginner. Never refuse."
)

USER_PROMPT = (
    "TASK:\n"
    "1) Read the chart image and propose a SPOT DCA plan (LONG-only).\n"
    "2) FIRST LINE: exactly ONE line JSON (no code fences) per schema.\n"
    "3) Then explain in Russian for a beginner (plain text, no markdown).\n"
    "4) DCA list must have 4-5 steps with valid prices and alloc_pct (sum ~100%).\n"
)


def _normalize_dca(steps: list[dict], base_price: float | None) -> list[dict]:
    if not steps:
        if base_price:
            return [
                {"price": base_price, "alloc_pct": 40},
                {"price": base_price * 0.97, "alloc_pct": 25},
                {"price": base_price * 0.94, "alloc_pct": 15},
                {"price": base_price * 0.90, "alloc_pct": 10},
                {"price": base_price * 0.85, "alloc_pct": 10},
            ]
        return []

    while len(steps) < 5:
        last_price = safe_float(steps[-1].get("price")) or (base_price or 100)
        steps.append({"price": round(last_price * 0.95, 2), "alloc_pct": 5})

    total_alloc = sum(s.get("alloc_pct", 0) for s in steps[:5])
    if total_alloc > 0:
        for s in steps[:5]:
            s["alloc_pct"] = round((s.get("alloc_pct", 0) / total_alloc) * 100, 1)

    return steps[:5]


async def handle_investor_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    status_msg = await msg.reply_text("💡 Строю DCA-план...")

    try:
        image_bytes = await extract_image_bytes(update, context)
        if not image_bytes:
            await status_msg.edit_text("❌ Не вижу изображения. Пришлите скрин как фото (PNG/JPG).")
            return

        img_b64 = to_jpeg_base64(image_bytes)
        client = get_deepseek_client()

        response = await client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            temperature=0.1,
            messages=[
                {"role": "system", "content": INVESTOR_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": USER_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]}
            ],
        )

        content = (response.choices[0].message.content or "").strip()

        data = {"direction": "LONG", "entry": None, "avg_entry": None, "stop": None, "tp": [], "dca": [], "notes": []}
        lines = content.splitlines()
        if lines:
            try:
                parsed = json.loads(lines[0])
                if isinstance(parsed, dict):
                    data = parsed
            except (json.JSONDecodeError, TypeError):
                pass

        entry = safe_float(data.get("entry"))
        dca_raw = data.get("dca") or []
        dca_steps = _normalize_dca(dca_raw, entry)

        wsum = sum(s.get("alloc_pct", 0) for s in dca_steps)
        psum = sum((safe_float(s.get("price")) or 0) * s.get("alloc_pct", 0) for s in dca_steps)
        avg_entry = round(psum / wsum, 2) if wsum > 0 else None

        tps = [safe_float(x) for x in (data.get("tp") or []) if safe_float(x) is not None]
        if avg_entry and not tps:
            tps = [round(avg_entry * 1.05, 2), round(avg_entry * 1.10, 2)]

        parts = [
            "💡 DCA Инвестиционный план (SPOT, LONG only):\n",
            f"0️⃣ Суть: Долгосрок, без плеча, 5 ступеней DCA",
        ]

        dca_lines = []
        for i, s in enumerate(dca_steps, 1):
            p = fmt_price(safe_float(s.get("price")))
            a = fmt_pct(safe_float(s.get("alloc_pct")))
            dca_lines.append(f"  {i}. Купить {a} по {p}")
        parts.append("1️⃣ План покупок:\n" + "\n".join(dca_lines))

        if avg_entry:
            parts.append(f"2️⃣ Средняя цена входа: {fmt_price(avg_entry)}")

        if tps:
            tps_str = ", ".join(fmt_price(x) for x in tps[:3])
            parts.append(f"3️⃣ Цели (TP): {tps_str}")

        potential = None
        if avg_entry and tps:
            potential = round((tps[0] - avg_entry) / avg_entry * 100, 1)
        if potential:
            parts.append(f"4️⃣ Потенциал к TP1: +{potential}%")

        notes = [str(n).strip() for n in (data.get("notes") or []) if str(n).strip()]
        if notes:
            parts.append("⚠️ Комментарии:\n" + "\n".join(f"• {n}" for n in notes[:5]))

        parts.append("\n✅ Доля позиции в портфеле — до 10-20%. Фиксируйте прибыль по целям.")

        await status_msg.edit_text("\n".join(parts))

    except Exception as e:
        logger.exception("Investor analysis failed")
        await status_msg.edit_text(f"❌ Не удалось построить DCA-план. Попробуйте другой скрин. ({str(e)[:100]})")
