"""Liquidity gate: >= $300M 24h quote volume before a signal may go public."""

from app.services.market_data.symbols import passes_liquidity_filter


class TestLiquidityFilter:
    def test_above_threshold_passes(self):
        assert passes_liquidity_filter(500_000_000.0, 300_000_000) is True

    def test_exact_threshold_passes(self):
        assert passes_liquidity_filter(300_000_000.0, 300_000_000) is True

    def test_below_threshold_rejected(self):
        assert passes_liquidity_filter(299_999_999.0, 300_000_000) is False

    def test_unknown_volume_fails_closed(self):
        assert passes_liquidity_filter(None, 300_000_000) is False
