import re
from decimal import Decimal


def safe_float(x) -> float | None:
    try:
        if x is None:
            return None
        return float(str(x).replace(" ", "").replace(",", "."))
    except (ValueError, TypeError):
        return None


def round2(x: float | None) -> float | None:
    return None if x is None else round(float(x), 2)


def calc_rr(entry: float | None, stop: float | None, tp: float | None) -> float | None:
    try:
        if entry is None or stop is None or tp is None:
            return None
        risk = abs(entry - stop)
        if risk <= 0:
            return None
        reward = abs(tp - entry)
        return round(reward / risk, 2)
    except Exception:
        return None


def fmt_price(price: float | None) -> str:
    if price is None:
        return "—"
    if price >= 100:
        return f"${price:,.2f}"
    if price >= 1:
        return f"${price:.4f}"
    return f"${price:.8f}"


def fmt_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:.1f}%"


def parse_price(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        cleaned = re.sub(r"[^\d.,\-]", "", raw).replace(",", ".").replace("$", "")
        return float(cleaned)
    except ValueError:
        return None


def parse_entry_stop_tp(text: str) -> tuple[float | None, float | None, float | None]:
    entry = None
    stop = None
    tp = None

    m = re.search(r"(Entry|Вход)[:\s]*\$?\s*([\d\s,.]+)", text, re.IGNORECASE)
    if m:
        entry = parse_price(m.group(2))

    m = re.search(r"(StopLoss|Стоп)[:\s]*\$?\s*([\d\s,.]+)", text, re.IGNORECASE)
    if m:
        stop = parse_price(m.group(2))

    m = re.search(r"(TakeProfit|Тейк|TP1)[:\s]*\$?\s*([\d\s,.]+)", text, re.IGNORECASE)
    if m:
        tp = parse_price(m.group(2))

    return entry, stop, tp


def sanitize_username(u: str | None) -> str:
    if not u:
        return "nouser"
    return re.sub(r"[^\w]+", "", u)[:32]


MONTHLY_PRICE_USD = 25
LIFETIME_PRICE_USD = 199
