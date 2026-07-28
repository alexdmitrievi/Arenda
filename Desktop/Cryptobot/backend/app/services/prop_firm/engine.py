from decimal import Decimal

from app.models.portfolio import ChallengeStatus, PropFirmChallenge

PROP_FIRM_RULES = {
    "hashhadge": {
        "name": "Hashhadge",
        "max_daily_loss_pct": 5.0,
        "max_trailing_dd_pct": 10.0,
        "profit_target_pct": 8.0,
        "min_trading_days": 5,
        "max_position_risk_pct": 2.0,
        "max_exposure_pct": 50.0,
        "account_sizes": [10000, 25000, 50000, 100000, 200000],
        "price_usd": {10000: 50, 25000: 125, 50000: 250, 100000: 500, 200000: 1000},
    },
    "ftmo": {
        "name": "FTMO",
        "max_daily_loss_pct": 5.0,
        "max_trailing_dd_pct": 10.0,
        "profit_target_pct": 10.0,
        "min_trading_days": 4,
        "max_position_risk_pct": 2.0,
        "max_exposure_pct": 50.0,
        "account_sizes": [10000, 25000, 50000, 100000, 200000],
        "price_usd": {10000: 155, 25000: 250, 50000: 500, 100000: 1000, 200000: 2000},
    },
    "tft": {
        "name": "The Funded Trader",
        "max_daily_loss_pct": 5.0,
        "max_trailing_dd_pct": 10.0,
        "profit_target_pct": 8.0,
        "min_trading_days": 5,
        "max_position_risk_pct": 2.0,
        "max_exposure_pct": 50.0,
        "account_sizes": [25000, 50000, 100000, 200000],
        "price_usd": {25000: 200, 50000: 400, 100000: 800, 200000: 1600},
    },
}


def get_firm_rules(firm: str) -> dict | None:
    return PROP_FIRM_RULES.get(firm.lower())


def check_daily_loss(progress: dict, firm_rules: dict) -> dict:
    daily_pnl = float(progress.get("daily_pnl", 0))
    starting_balance = float(progress.get("starting_equity", 0))
    max_daily = starting_balance * firm_rules["max_daily_loss_pct"] / 100
    used_pct = abs(daily_pnl) / max_daily * 100 if max_daily > 0 else 0

    return {
        "ok": abs(daily_pnl) <= max_daily,
        "current_loss": round(daily_pnl, 2),
        "max_daily_loss": round(max_daily, 2),
        "used_pct": round(used_pct, 1),
        "remaining": round(max_daily + daily_pnl, 2),
    }


def check_trailing_dd(progress: dict, firm_rules: dict) -> dict:
    peak = float(progress.get("peak_equity", 0))
    current = float(progress.get("current_equity", 0))
    max_dd_pct = firm_rules["max_trailing_dd_pct"]

    dd_pct = (1 - current / peak) * 100 if peak > 0 else 0

    return {
        "ok": dd_pct <= max_dd_pct,
        "current_dd_pct": round(dd_pct, 2),
        "max_dd_pct": max_dd_pct,
        "peak_equity": round(peak, 2),
        "current_equity": round(current, 2),
    }


def check_profit_target(progress: dict, firm_rules: dict) -> dict:
    starting = float(progress.get("starting_equity", 0))
    current = float(progress.get("current_equity", 0))
    target_pct = firm_rules["profit_target_pct"]

    achieved_pct = (current - starting) / starting * 100 if starting > 0 else 0

    return {
        "achieved": achieved_pct >= target_pct,
        "achieved_pct": round(achieved_pct, 2),
        "target_pct": target_pct,
        "remaining_pct": round(max(0, target_pct - achieved_pct), 2),
    }


def update_challenge_progress(
    challenge: PropFirmChallenge,
    current_equity: float,
    daily_pnl: float,
    trading_day: int,
) -> dict:
    progress = challenge.progress or {}
    rules = challenge.rules or {}

    progress["current_equity"] = current_equity
    progress["daily_pnl"] = daily_pnl

    if current_equity > progress.get("peak_equity", 0):
        progress["peak_equity"] = current_equity

    if not progress.get("starting_equity"):
        progress["starting_equity"] = current_equity - daily_pnl

    if not progress.get("trading_days_completed"):
        progress["trading_days_completed"] = 0
    progress["trading_days_completed"] = trading_day

    daily = check_daily_loss(progress, rules)
    dd = check_trailing_dd(progress, rules)
    pt = check_profit_target(progress, rules)

    if not daily["ok"] or not dd["ok"]:
        challenge.status = ChallengeStatus.FAILED
    elif pt["achieved"] and trading_day >= rules.get("min_trading_days", 5):
        challenge.status = ChallengeStatus.PASSED

    challenge.progress = progress
    return {
        "daily_loss": daily,
        "trailing_dd": dd,
        "profit_target": pt,
        "trading_days": {"current": trading_day, "required": rules.get("min_trading_days", 5)},
        "status": challenge.status.value,
    }
