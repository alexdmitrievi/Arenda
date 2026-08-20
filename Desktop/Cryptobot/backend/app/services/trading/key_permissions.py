"""Bybit API-key permission validation.

Keys with wallet rights (withdrawal/transfer) must never be accepted by the
platform: the trading code only places orders, but a leaked key with wallet
rights is a direct route to moving funds out. The check is fail-closed —
if the exchange cannot answer, the keys are not saved.
"""

import logging

logger = logging.getLogger("tbx.trading.key_permissions")

# permission groups and the rights that make a key unacceptable
DANGEROUS_PERMISSIONS = {
    "Withdrawal",
    "AccountTransfer",
    "SubAccountTransfer",
    "CollateralTransfer",
    "CoinSwap",
}
REQUIRED_SPOT_PERMISSION = "SpotTrade"
CONTRACT_TRADE_RIGHTS = {"Order", "Position"}


def parse_permission_groups(query_api_response: dict) -> dict[str, list[str]]:
    """Extract {"Spot": [...], "ContractTrade": [...], "Wallet": [...]} from
    the GET /v5/user/query-api response."""
    result = query_api_response.get("result") or {}
    permissions = result.get("permissions") or {}
    groups: dict[str, list[str]] = {}
    for group, rights in permissions.items():
        groups[str(group)] = [str(r) for r in (rights or [])]
    return groups


def check_permissions(groups: dict[str, list[str]]) -> list[str]:
    """Return the list of problems; empty means the key is acceptable.

    Accepts keys able to trade spot (SpotTrade) and/or USDT-M perpetuals
    (ContractTrade: Order/Position). Wallet rights are always rejected.
    """
    problems: list[str] = []
    all_rights = {right for rights in groups.values() for right in rights}
    dangerous = sorted(DANGEROUS_PERMISSIONS & all_rights)
    if dangerous:
        problems.append(f"wallet rights present: {', '.join(dangerous)}")
    spot_rights = set(groups.get("Spot", []))
    contract_rights = set(groups.get("ContractTrade", []))
    can_trade_spot = REQUIRED_SPOT_PERMISSION in spot_rights
    can_trade_perps = bool(contract_rights & CONTRACT_TRADE_RIGHTS)
    if not can_trade_spot and not can_trade_perps:
        problems.append(
            f"neither spot '{REQUIRED_SPOT_PERMISSION}' nor perp trading rights "
            "(ContractTrade: Order/Position) are present"
        )
    return problems


async def fetch_bybit_key_permissions(exchange) -> dict[str, list[str]]:
    """Query the key-info endpoint through the exchange client."""
    response = await exchange.private_get_v5_user_query_api()
    return parse_permission_groups(response)
