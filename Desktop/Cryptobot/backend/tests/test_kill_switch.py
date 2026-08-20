"""Kill switch: halt flag semantics and spot liquidation."""

import json

import pytest

from app.services.trading import killswitch


class _FakeRedis:
    def __init__(self, data=None, fail=False):
        self.data = data if data is not None else {}
        self.fail = fail

    async def get(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        return self.data.get(key)

    async def set(self, key, value):
        if self.fail:
            raise RuntimeError("redis down")
        self.data[key] = value

    async def delete(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        self.data.pop(key, None)


def _fake_get_redis(fake):
    async def _get_redis():
        return fake
    return _get_redis


@pytest.mark.asyncio
async def test_not_halted_by_default(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(killswitch, "get_redis", _fake_get_redis(fake))
    assert await killswitch.is_trading_halted() is False


@pytest.mark.asyncio
async def test_halted_when_flag_set(monkeypatch):
    fake = _FakeRedis({killswitch.HALT_KEY: json.dumps({"reason": "test"})})
    monkeypatch.setattr(killswitch, "get_redis", _fake_get_redis(fake))
    assert await killswitch.is_trading_halted() is True


@pytest.mark.asyncio
async def test_fails_closed_when_redis_down(monkeypatch):
    fake = _FakeRedis(fail=True)
    monkeypatch.setattr(killswitch, "get_redis", _fake_get_redis(fake))
    assert await killswitch.is_trading_halted() is True


@pytest.mark.asyncio
async def test_set_clear_roundtrip(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(killswitch, "get_redis", _fake_get_redis(fake))
    await killswitch.set_trading_halt("market chaos")
    assert await killswitch.is_trading_halted() is True
    info = await killswitch.get_trading_halt_info()
    assert info["reason"] == "market chaos"
    await killswitch.clear_trading_halt()
    assert await killswitch.is_trading_halted() is False


class _FakeExchange:
    def __init__(self):
        self.closes = []

    async def fetch_positions(self):
        return [
            {"symbol": "BTC/USDT:USDT", "contracts": 0.5, "side": "long"},
            {"symbol": "ETH/USDT:USDT", "contracts": 0.0, "side": "long"},
            {"symbol": "SOL/USDT:USDT", "contracts": -2.0, "side": "short"},
        ]

    def amount_to_precision(self, symbol, amount):
        return amount

    async def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        self.closes.append({"symbol": symbol, "side": side, "amount": amount, "params": params or {}})
        return {"id": f"id-{len(self.closes)}", "average": 100.0}


@pytest.mark.asyncio
async def test_close_all_positions_closes_open_perps():
    exchange = _FakeExchange()
    closed = await killswitch.close_all_positions(exchange)
    assert len(closed) == 2
    by_symbol = {c["symbol"]: c for c in closed}
    assert by_symbol["BTC/USDT:USDT"]["side"] == "sell"
    assert by_symbol["BTC/USDT:USDT"]["amount"] == 0.5
    assert by_symbol["SOL/USDT:USDT"]["side"] == "buy"
    assert by_symbol["SOL/USDT:USDT"]["amount"] == 2.0
    for order in exchange.closes:
        assert order["params"].get("reduceOnly") is True
