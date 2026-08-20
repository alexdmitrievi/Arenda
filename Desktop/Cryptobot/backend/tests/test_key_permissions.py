"""Bybit API-key permission validation."""

import pytest

from app.services.trading.key_permissions import (
    check_permissions,
    fetch_bybit_key_permissions,
    parse_permission_groups,
)


def _response(permissions: dict) -> dict:
    return {"retCode": 0, "result": {"permissions": permissions}}


class TestParsePermissionGroups:
    def test_parses_groups(self):
        groups = parse_permission_groups(_response({
            "Spot": ["SpotTrade"],
            "ContractTrade": [],
            "Wallet": ["AccountTransfer"],
        }))
        assert groups == {"Spot": ["SpotTrade"], "ContractTrade": [], "Wallet": ["AccountTransfer"]}

    def test_empty_when_missing(self):
        assert parse_permission_groups({"result": {}}) == {}


class TestCheckPermissions:
    def test_clean_spot_key_accepted(self):
        problems = check_permissions({"Spot": ["SpotTrade"], "Wallet": []})
        assert problems == []

    def test_withdrawal_rights_rejected(self):
        problems = check_permissions({"Spot": ["SpotTrade"], "Wallet": ["Withdrawal"]})
        assert any("Withdrawal" in p for p in problems)

    def test_transfer_rights_rejected(self):
        problems = check_permissions({
            "Spot": ["SpotTrade"],
            "ContractTrade": [],
            "Wallet": ["SubAccountTransfer", "CoinSwap"],
        })
        assert any("SubAccountTransfer" in p for p in problems)

    def test_missing_spot_trade_rejected(self):
        problems = check_permissions({"Spot": [], "Wallet": []})
        assert any("SpotTrade" in p for p in problems)

    def test_contract_trade_rights_accepted(self):
        problems = check_permissions({
            "Spot": [],
            "ContractTrade": ["Order", "Position"],
            "Wallet": [],
        })
        assert problems == []

    def test_contract_trade_with_withdrawal_rejected(self):
        problems = check_permissions({
            "ContractTrade": ["Order"],
            "Wallet": ["Withdrawal"],
        })
        assert any("Withdrawal" in p for p in problems)

    def test_no_trading_rights_rejected(self):
        problems = check_permissions({"Spot": [], "ContractTrade": [], "Wallet": []})
        assert any("SpotTrade" in p for p in problems)


class _FakeExchange:
    def __init__(self, response):
        self._response = response

    async def private_get_v5_user_query_api(self):
        return self._response


@pytest.mark.asyncio
async def test_fetch_permissions_roundtrip():
    exchange = _FakeExchange(_response({"Spot": ["SpotTrade"], "Wallet": []}))
    groups = await fetch_bybit_key_permissions(exchange)
    assert groups == {"Spot": ["SpotTrade"], "Wallet": []}
