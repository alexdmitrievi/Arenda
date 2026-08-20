"""DB <-> exchange sync: detecting exchange-side closes and recording them."""

import uuid
from decimal import Decimal

import pytest

from app.models.trade import Trade, TradeSide, TradeStatus
from app.services.trading.sync import (
    match_close_fills,
    record_trade_close,
    sync_trades_for_user,
)


def _fill(side: str, amount: float, price: float, fee_cost: float = 0.0) -> dict:
    return {"side": side, "amount": amount, "price": price, "fee": {"cost": fee_cost}}


class TestMatchCloseFills:
    def test_no_close_when_sells_below_size(self):
        fills = [_fill("sell", 0.4, 100.0)]
        matched, price, fee = match_close_fills(fills, "buy", size=1.0)
        assert matched == []

    def test_close_on_full_sell(self):
        fills = [_fill("buy", 1.0, 90.0), _fill("sell", 1.0, 100.0, fee_cost=0.55)]
        matched, price, fee = match_close_fills(fills, "buy", size=1.0)
        assert len(matched) == 1
        assert price == pytest.approx(100.0)
        assert fee == pytest.approx(0.55)

    def test_volume_weighted_price_across_fills(self):
        fills = [_fill("sell", 0.5, 100.0), _fill("sell", 0.5, 110.0)]
        _, price, _ = match_close_fills(fills, "buy", size=1.0)
        assert price == pytest.approx(105.0)

    def test_ignores_close_side_mismatch(self):
        fills = [_fill("sell", 1.0, 100.0)]
        matched, _, _ = match_close_fills(fills, "sell", size=1.0)  # a short is closed by a buy
        assert matched == []


def _trade(side: str = "buy", entry: float = 100.0, size: float = 1.0) -> Trade:
    return Trade(
        user_id=uuid.uuid4(),
        exchange="bybit",
        symbol="BTC/USDT",
        side=TradeSide.BUY if side == "buy" else TradeSide.SELL,
        entry_price=Decimal(str(entry)),
        size=Decimal(str(size)),
        status=TradeStatus.OPEN,
    )


class TestRecordTradeClose:
    def test_records_close_with_pnl(self):
        trade = _trade(entry=100.0, size=2.0)
        record_trade_close(trade, exit_price=105.0, fee_cost=1.0)
        assert trade.status == TradeStatus.CLOSED
        assert trade.exit_price == Decimal("105.0")
        assert float(trade.pnl) == pytest.approx(9.0)  # 2 * 5 - 1 fee
        assert float(trade.pnl_pct) == pytest.approx(4.5)  # 9 / 200 * 100
        assert trade.closed_at is not None

    def test_records_loss(self):
        trade = _trade(entry=100.0, size=1.0)
        record_trade_close(trade, exit_price=95.0)
        assert float(trade.pnl) == pytest.approx(-5.0)
        assert trade.status == TradeStatus.CLOSED


class _FakeExchange:
    def __init__(self, fills_by_symbol: dict):
        self.fills = fills_by_symbol

    async def fetch_my_trades(self, symbol, since=None, limit=200):
        return self.fills.get(symbol, [])


@pytest.mark.asyncio
async def test_sync_closes_trade_filled_on_exchange():
    trade = _trade()
    exchange = _FakeExchange({"BTC/USDT": [_fill("buy", 1.0, 90.0), _fill("sell", 1.0, 95.0)]})
    closed = await sync_trades_for_user(exchange, [trade])
    assert closed == [trade]
    assert trade.status == TradeStatus.CLOSED
    assert trade.exit_price == Decimal("95.0")


@pytest.mark.asyncio
async def test_sync_leaves_unfilled_trade_open():
    trade = _trade()
    exchange = _FakeExchange({"BTC/USDT": [_fill("buy", 1.0, 90.0)]})
    closed = await sync_trades_for_user(exchange, [trade])
    assert closed == []
    assert trade.status == TradeStatus.OPEN


@pytest.mark.asyncio
async def test_sync_survives_exchange_errors():
    trade = _trade()

    class BrokenExchange:
        async def fetch_my_trades(self, symbol, since=None, limit=200):
            raise RuntimeError("exchange down")

    closed = await sync_trades_for_user(BrokenExchange(), [trade])
    assert closed == []
    assert trade.status == TradeStatus.OPEN
