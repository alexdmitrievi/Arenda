from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass
class SignalResult:
    symbol: str
    direction: str  # "BUY" | "SELL" | "NONE"
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    confidence: int  # 0-100
    metadata: dict[str, Any]


@dataclass
class BacktestResult:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    trades: list[dict]


class AbstractStrategy(ABC):
    name: str = "base"
    timeframe: str = "4h"

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> SignalResult:
        ...

    def backtest(self, df: pd.DataFrame, symbol: str = "") -> BacktestResult:
        trades = []
        position = None
        entry_price = 0.0
        stop_loss = 0.0
        take_profit = 0.0
        direction = ""

        equity_curve = []
        peak = 0.0
        max_dd = 0.0

        for i in range(200, len(df)):
            window = df.iloc[i - 200 : i].copy()
            signal = self.generate_signal(window, symbol)

            current_price = df.iloc[i]["close"]

            if position is None and signal.direction in ("BUY", "SELL"):
                position = signal
                entry_price = signal.entry or current_price
                stop_loss = signal.stop_loss or (entry_price * 0.95)
                take_profit = signal.take_profit[0] if signal.take_profit else entry_price * 1.05
                direction = signal.direction

            if position is not None:
                if direction == "BUY":
                    if current_price <= stop_loss:
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                        trades.append({"entry": entry_price, "exit": current_price,
                                       "pnl_pct": pnl_pct, "side": "BUY", "result": "SL"})
                        position = None
                    elif current_price >= take_profit:
                        pnl_pct = (current_price - entry_price) / entry_price * 100
                        trades.append({"entry": entry_price, "exit": current_price,
                                       "pnl_pct": pnl_pct, "side": "BUY", "result": "TP"})
                        position = None
                else:
                    if current_price >= stop_loss:
                        pnl_pct = (entry_price - current_price) / entry_price * 100
                        trades.append({"entry": entry_price, "exit": current_price,
                                       "pnl_pct": pnl_pct, "side": "SELL", "result": "SL"})
                        position = None
                    elif current_price <= take_profit:
                        pnl_pct = (entry_price - current_price) / entry_price * 100
                        trades.append({"entry": entry_price, "exit": current_price,
                                       "pnl_pct": pnl_pct, "side": "SELL", "result": "TP"})
                        position = None

            if trades:
                eq = sum(t["pnl_pct"] for t in trades)
                equity_curve.append(eq)
                peak = max(peak, eq)
                dd = peak - eq
                max_dd = max(max_dd, dd)

        wins = [t for t in trades if t["pnl_pct"] > 0]
        total_pnl = sum(t["pnl_pct"] for t in trades)
        gross_profit = sum(t["pnl_pct"] for t in wins)
        gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0)) or 0.01

        return BacktestResult(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(trades) - len(wins),
            win_rate=round(len(wins) / len(trades) * 100, 1) if trades else 0,
            total_pnl_pct=round(total_pnl, 2),
            profit_factor=round(gross_profit / gross_loss, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=round(total_pnl / (max_dd + 0.01), 2),
            trades=trades,
        )
