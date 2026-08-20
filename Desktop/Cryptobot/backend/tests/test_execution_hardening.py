"""Execution hardening: RR enforcement, 2% risk sizing, stop verification."""

import pytest

from app.services.trading.execution import (
    StopLossFailure,
    compute_position_size,
    ensure_stop_attached,
    position_metrics,
    stop_zone_and_rr,
    validate_geometry,
)


class TestValidateGeometry:
    def test_rejects_missing_tp(self):
        with pytest.raises(ValueError):
            validate_geometry(entry=100.0, stop=98.0, tp=None)

    def test_rejects_rr_below_two(self):
        with pytest.raises(ValueError):
            validate_geometry(entry=100.0, stop=98.0, tp=103.0)  # RR 1.5:1

    def test_accepts_rr_two(self):
        validate_geometry(entry=100.0, stop=98.0, tp=104.0)  # RR 2:1

    def test_accepts_rr_three(self):
        validate_geometry(entry=100.0, stop=98.0, tp=106.0)  # RR 3:1

    def test_accepts_rr_above_three(self):
        validate_geometry(entry=100.0, stop=98.0, tp=110.0)

    def test_rejects_zero_stop_distance(self):
        with pytest.raises(ValueError):
            validate_geometry(entry=100.0, stop=100.0, tp=110.0)


class TestPositionSize:
    def test_two_percent_risk(self):
        # $1000 balance, 2% risk = $20 over a $2 stop distance → 10 units
        size = compute_position_size(balance=1000.0, risk_pct=2.0, entry=100.0, stop=98.0)
        assert size == pytest.approx(10.0)

    def test_custom_risk_pct(self):
        size = compute_position_size(balance=1000.0, risk_pct=1.0, entry=100.0, stop=98.0)
        assert size == pytest.approx(5.0)

    def test_rejects_invalid_stop_distance(self):
        with pytest.raises(ValueError):
            compute_position_size(balance=1000.0, risk_pct=2.0, entry=100.0, stop=100.0)


class TestPositionMetrics:
    def test_owner_calculator_example(self):
        # deposit $1000, risk 2%, stop zone 7% → volume $285.71 (the calculator's answer)
        m = position_metrics(entry=100.0, stop=93.0, tp=121.0,
                             balance=1000.0, risk_pct=2.0, leverage=1)
        assert m["stop_zone_pct"] == 7.0
        assert m["risk_amount"] == 20.0
        assert m["position_volume_usd"] == pytest.approx(285.71, abs=0.01)
        assert m["position_size_base"] == pytest.approx(2.8571, abs=1e-4)
        assert m["margin_required"] == pytest.approx(285.71, abs=0.01)
        assert m["rr"] == 3.0

    def test_leverage_does_not_change_volume(self):
        m1 = position_metrics(entry=100.0, stop=93.0, tp=121.0,
                              balance=1000.0, risk_pct=2.0, leverage=1)
        m5 = position_metrics(entry=100.0, stop=93.0, tp=121.0,
                              balance=1000.0, risk_pct=2.0, leverage=5)
        assert m1["position_volume_usd"] == m5["position_volume_usd"]
        assert m5["margin_required"] == pytest.approx(285.71 / 5, abs=0.01)

    def test_stop_zone_and_rr_helper(self):
        zone, rr = stop_zone_and_rr(entry=100.0, stop=93.0, tp=121.0)
        assert zone == 7.0
        assert rr == 3.0
        zone2, rr2 = stop_zone_and_rr(entry=100.0, stop=100.0, tp=None)
        assert zone2 == 0.0
        assert rr2 is None


class _FakeExchange:
    def __init__(self, open_orders=None, stop_fails=False):
        self._open_orders = open_orders or []
        self._stop_fails = stop_fails
        self.placed = []

    async def fetch_open_orders(self, symbol):
        return list(self._open_orders)

    async def create_order(self, symbol, order_type, side, amount, price, params):
        if self._stop_fails and params.get("triggerPrice"):
            raise RuntimeError("exchange refused stop order")
        self.placed.append({"symbol": symbol, "side": side, "params": params})
        return {"id": f"order-{len(self.placed)}"}


class TestEnsureStopAttached:
    @pytest.mark.asyncio
    async def test_places_missing_stop_and_tp(self, monkeypatch):
        exchange = _FakeExchange()
        result = await ensure_stop_attached(
            exchange, "BTC/USDT", "buy", 1.0, stop_price=95.0, tp_price=115.0
        )
        assert result["stop_order_id"] == "order-1"
        assert result["tp_order_id"] == "order-2"
        sides = [p["side"] for p in exchange.placed]
        assert sides == ["sell", "sell"]

    @pytest.mark.asyncio
    async def test_reuses_existing_stop(self):
        existing = [
            {"id": "stop-9", "triggerPrice": 95.0},
            {"id": "tp-9", "triggerPrice": 115.0},
        ]
        exchange = _FakeExchange(open_orders=existing)
        result = await ensure_stop_attached(
            exchange, "BTC/USDT", "buy", 1.0, stop_price=95.0, tp_price=115.0
        )
        assert result == {"stop_order_id": "stop-9", "tp_order_id": "tp-9"}
        assert exchange.placed == []

    @pytest.mark.asyncio
    async def test_raises_when_stop_cannot_be_placed(self):
        exchange = _FakeExchange(stop_fails=True)
        with pytest.raises(StopLossFailure):
            await ensure_stop_attached(
                exchange, "BTC/USDT", "buy", 1.0, stop_price=95.0, tp_price=None
            )
