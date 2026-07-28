from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd

from app.models.portfolio import DCAFrequency, DCAPlan
from app.services.trading.market_data import get_latest_price


async def calculate_dynamic_steps(
    plan: DCAPlan,
    current_price: float,
    redis_client,
) -> list[dict]:
    amount = float(plan.amount_per_period)
    atr_mult = float(plan.atr_multiplier)
    steps = []

    base_allocs = [40, 25, 15, 10, 10]

    for i, alloc in enumerate(base_allocs):
        discount = 1.0 + (i * float(atr_mult) * 0.01)
        step_price = round(current_price / discount, 4)
        steps.append({
            "step": i + 1,
            "price": step_price,
            "alloc_pct": alloc,
            "amount": round(amount * alloc / 100, 2),
            "quantity": round(amount * alloc / 100 / step_price, 6) if step_price > 0 else 0,
        })

    return steps


def get_next_execution(frequency: DCAFrequency) -> datetime:
    now = datetime.now(timezone.utc)
    if frequency == DCAFrequency.DAILY:
        return now + timedelta(days=1)
    elif frequency == DCAFrequency.WEEKLY:
        return now + timedelta(days=7)
    monthly = now.replace(day=min(now.day, 28)) + timedelta(days=32)
    return monthly.replace(day=1)
