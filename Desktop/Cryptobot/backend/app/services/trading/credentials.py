"""Shared access to a user's stored exchange credentials."""

from app.core.security import decrypt_api_key


def get_bybit_credentials(user) -> tuple[str, str] | None:
    """Decrypt a user's Bybit API key/secret, or None if not configured."""
    user_keys = user.exchange_keys_encrypted or {}
    bybit_keys = user_keys.get("bybit", {})
    api_key = bybit_keys.get("api_key")
    secret = bybit_keys.get("secret")
    if not api_key or not secret:
        return None
    return decrypt_api_key(api_key), decrypt_api_key(secret)


def user_risk_pct(user) -> float:
    """Risk per trade in % of balance, default 2% (product mandate)."""
    bybit_keys = (user.exchange_keys_encrypted or {}).get("bybit", {})
    try:
        value = float(bybit_keys.get("risk_per_trade_pct", 2.0))
    except (TypeError, ValueError):
        return 2.0
    return max(0.1, min(10.0, value))
