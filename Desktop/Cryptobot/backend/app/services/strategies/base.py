from abc import ABC, abstractmethod
from dataclasses import dataclass, field
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
    expectancy_pct: float = 0.0  # avg net pnl per trade — THE metric that matters
    costs_pct: float = 0.0  # total fees+slippage+funding paid, in %
    expired_signals: int = 0  # signals whose entry was never touched


# Bybit taker fee per side; entries are limit orders but we still charge
# taker on both legs to stay conservative
TAKER_FEE = 0.00055
SLIPPAGE = 0.0003  # market-exit slippage assumption
FUNDING_PER_8H = 0.0001  # average perp funding per 8h held
ENTRY_TTL_BARS = 24  # unfilled limit entries expire after a day (1h bars)


class AbstractStrategy(ABC):
    name: str = "base"
    timeframe: str = "4h"

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str = "") -> SignalResult:
        ...

    def backtest(self, df: pd.DataFrame, symbol: str = "") -> BacktestResult:
        """Look-ahead-free simulation.

        Rules that keep it honest:
        - a signal produced on window [i-200, i) may only be acted on from bar i;
        - a limit entry fills only when a later bar actually trades through it;
        - SL/TP are evaluated on the bar's high/low, not its close;
        - if both entry+SL (or SL+TP) fit in one bar, the STOP wins — worst case;
        - every closed trade pays fees, slippage and funding.
        """
        trades: list[dict] = []
        pending: dict | None = None
        position: dict | None = None
        expired = 0

        equity = 0.0
        peak = 0.0
        max_dd = 0.0

        for i in range(200, len(df)):
            bar = df.iloc[i]
            high, low = float(bar["high"]), float(bar["low"])

            # 1) pending limit order: expire or fill
            if pending is not None:
                pending["age"] += 1
                filled = (
                    low <= pending["entry"] if pending["direction"] == "BUY"
                    else high >= pending["entry"]
                )
                # invalidation: price ran to the stop before ever giving the entry
                invalidated = (
                    low <= pending["stop"] if pending["direction"] == "BUY"
                    else high >= pending["stop"]
                )
                if filled:
                    position = {**pending, "held_bars": 0}
                    pending = None
                    # worst case: the same bar also spans the stop
                    if invalidated:
                        trades.append(self._close_trade(position, position["stop"], "SL"))
                        position = None
                elif invalidated or pending["age"] >= ENTRY_TTL_BARS:
                    expired += 1
                    pending = None

            # 2) open position: stop first (conservative), then target
            elif position is not None:
                position["held_bars"] += 1
                if position["direction"] == "BUY":
                    if low <= position["stop"]:
                        trades.append(self._close_trade(position, position["stop"], "SL"))
                        position = None
                    elif high >= position["tp"]:
                        trades.append(self._close_trade(position, position["tp"], "TP"))
                        position = None
                else:
                    if high >= position["stop"]:
                        trades.append(self._close_trade(position, position["stop"], "SL"))
                        position = None
                    elif low <= position["tp"]:
                        trades.append(self._close_trade(position, position["tp"], "TP"))
                        position = None

            # 3) flat and no pending order: look for a new signal
            if position is None and pending is None:
                window = df.iloc[i - 200: i]
                signal = self.generate_signal(window, symbol)
                if signal.direction in ("BUY", "SELL") and signal.entry and signal.stop_loss:
                    tp = signal.take_profit[0] if signal.take_profit else None
                    if tp:
                        pending = {
                            "direction": signal.direction,
                            "entry": float(signal.entry),
                            "stop": float(signal.stop_loss),
                            "tp": float(tp),
                            "age": 0,
                        }

            if trades:
                equity = sum(t["pnl_pct"] for t in trades)
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)

        wins = [t for t in trades if t["pnl_pct"] > 0]
        total_pnl = sum(t["pnl_pct"] for t in trades)
        total_costs = sum(t["costs_pct"] for t in trades)
        gross_profit = sum(t["pnl_pct"] for t in wins)
        gross_loss = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0)) or 0.01

        pnls = [t["pnl_pct"] for t in trades]
        if len(pnls) > 1:
            mean = total_pnl / len(pnls)
            variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
            std = variance ** 0.5
            sharpe = round(mean / std * (len(pnls) ** 0.5), 2) if std > 0 else 0.0
        else:
            sharpe = 0.0

        return BacktestResult(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(trades) - len(wins),
            win_rate=round(len(wins) / len(trades) * 100, 1) if trades else 0,
            total_pnl_pct=round(total_pnl, 2),
            profit_factor=round(gross_profit / gross_loss, 2),
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=sharpe,
            trades=trades,
            expectancy_pct=round(total_pnl / len(trades), 3) if trades else 0.0,
            costs_pct=round(total_costs, 2),
            expired_signals=expired,
        )

    @staticmethod
    def _close_trade(position: dict, exit_price: float, result: str) -> dict:
        entry = position["entry"]
        direction = 1 if position["direction"] == "BUY" else -1
        gross_pct = (exit_price - entry) / entry * 100 * direction

        # SL exits are market orders → slippage; TP exits are limits
        slippage = SLIPPAGE if result == "SL" else 0.0
        funding = FUNDING_PER_8H * (position.get("held_bars", 0) / 8)
        costs_pct = (TAKER_FEE * 2 + slippage + funding) * 100

        return {
            "entry": entry,
            "exit": exit_price,
            "side": position["direction"],
            "result": result,
            "held_bars": position.get("held_bars", 0),
            "costs_pct": round(costs_pct, 4),
            "pnl_pct": round(gross_pct - costs_pct, 4),
        }
