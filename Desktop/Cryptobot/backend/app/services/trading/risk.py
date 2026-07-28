from decimal import Decimal
from typing import Any


def calculate_position_size(
    balance: float,
    risk_pct: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: int = 1,
) -> tuple[float, float, float]:
    risk_amount = balance * (risk_pct / 100)
    stop_distance = abs(entry_price - stop_loss_price)
    if stop_distance <= 0:
        raise ValueError("Stop-loss distance must be positive")

    position_size_quote = risk_amount / (stop_distance / entry_price)
    position_size_base = position_size_quote / entry_price

    position_size_quote = round(position_size_quote, 2)
    position_size_base = round(position_size_base, 6)

    return risk_amount, position_size_quote, position_size_base


class DailyLossTracker:
    def __init__(self, starting_balance: float, max_daily_loss_pct: float = 5.0):
        self.starting_balance = starting_balance
        self.max_daily_loss = starting_balance * (max_daily_loss_pct / 100)
        self.current_pnl = 0.0

    def update_pnl(self, pnl: float):
        self.current_pnl += pnl

    @property
    def remaining_loss_capacity(self) -> float:
        return self.max_daily_loss + self.current_pnl

    @property
    def is_limit_hit(self) -> bool:
        return self.current_pnl <= -self.max_daily_loss

    @property
    def usage_pct(self) -> float:
        if self.max_daily_loss <= 0:
            return 100.0
        return round(abs(self.current_pnl) / self.max_daily_loss * 100, 1)


class DrawdownTracker:
    def __init__(self, max_trailing_dd_pct: float = 10.0):
        self.max_trailing_dd_pct = max_trailing_dd_pct
        self.peak_equity = 0.0
        self.current_equity = 0.0

    def update(self, current_equity: float):
        self.current_equity = current_equity
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return round((1 - self.current_equity / self.peak_equity) * 100, 2)

    @property
    def is_limit_hit(self) -> bool:
        return self.drawdown_pct >= self.max_trailing_dd_pct


class RiskManager:
    def __init__(
        self,
        balance: float,
        max_risk_per_trade_pct: float = 2.0,
        max_daily_loss_pct: float = 5.0,
        max_trailing_dd_pct: float = 10.0,
        max_exposure_pct: float = 50.0,
        max_positions: int = 5,
    ):
        self.balance = balance
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_exposure_pct = max_exposure_pct
        self.max_positions = max_positions
        self.daily_loss = DailyLossTracker(balance, max_daily_loss_pct)
        self.drawdown = DrawdownTracker(max_trailing_dd_pct)
        self.open_positions_count = 0
        self.total_exposure = 0.0

    def can_open_position(
        self,
        risk_pct: float,
        position_size_quote: float,
    ) -> tuple[bool, str]:
        if self.daily_loss.is_limit_hit:
            return False, f"Daily loss limit reached ({self.daily_loss.usage_pct}%)"

        if self.drawdown.is_limit_hit:
            return False, f"Trailing drawdown limit reached ({self.drawdown.drawdown_pct}%)"

        if self.open_positions_count >= self.max_positions:
            return False, f"Max positions reached ({self.max_positions})"

        if risk_pct > self.max_risk_per_trade_pct:
            return False, f"Risk {risk_pct}% exceeds max {self.max_risk_per_trade_pct}%"

        new_exposure = (self.total_exposure + position_size_quote) / self.balance * 100
        if new_exposure > self.max_exposure_pct:
            return False, f"Exposure {new_exposure:.1f}% exceeds max {self.max_exposure_pct}%"

        return True, "OK"

    def register_position(self, position_size_quote: float):
        self.open_positions_count += 1
        self.total_exposure += position_size_quote

    def close_position(self, position_size_quote: float, pnl: float):
        self.open_positions_count = max(0, self.open_positions_count - 1)
        self.total_exposure = max(0, self.total_exposure - position_size_quote)
        self.daily_loss.update_pnl(pnl)

    def update_equity(self, equity: float):
        self.drawdown.update(equity)

    def reset_daily(self, new_balance: float):
        self.daily_loss = DailyLossTracker(new_balance, self.daily_loss.max_daily_loss / new_balance * 100)
