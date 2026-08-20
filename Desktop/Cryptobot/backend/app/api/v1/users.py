import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.security import decrypt_api_key, encrypt_api_key
from app.schemas.user import (
    ExchangeKeyResponse,
    ExchangeKeySet,
    UserProfileResponse,
    UserProfileUpdate,
)

logger = logging.getLogger("tbx.api.users")

router = APIRouter()


def _build_profile(user) -> UserProfileResponse:
    exchanges = []
    if user.exchange_keys_encrypted:
        for ex, _ in user.exchange_keys_encrypted.items():
            exchanges.append(ex)

    return UserProfileResponse(
        id=str(user.id),
        telegram_id=user.telegram_id,
        username=user.username,
        email=user.email,
        email_verified=user.email_verified,
        role=user.role.value,
        is_active=user.is_active,
        has_exchange_keys=bool(exchanges),
        avatar_url=user.avatar_url,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(current_user: CurrentUser):
    return _build_profile(current_user)


@router.patch("/me", response_model=UserProfileResponse)
async def update_my_profile(
    data: UserProfileUpdate,
    current_user: CurrentUser,
):
    if data.username is not None:
        current_user.username = data.username
    if data.email is not None:
        current_user.email = data.email
        current_user.email_verified = False
    if data.avatar_url is not None:
        current_user.avatar_url = data.avatar_url

    return _build_profile(current_user)


@router.put("/me/exchange-keys")
async def set_exchange_keys(
    data: ExchangeKeySet,
    current_user: CurrentUser,
):
    current_keys = dict(current_user.exchange_keys_encrypted or {})

    key_data: dict = {
        "api_key": encrypt_api_key(data.api_key),
        "secret": encrypt_api_key(data.secret),
    }
    if data.passphrase:
        key_data["passphrase"] = encrypt_api_key(data.passphrase)
    if data.risk_per_trade_pct is not None:
        key_data["risk_per_trade_pct"] = data.risk_per_trade_pct

    if data.exchange.lower() == "bybit":
        await _verify_bybit_key_permissions(data.api_key, data.secret, data.passphrase, key_data)

    current_keys[data.exchange.lower()] = key_data
    current_user.exchange_keys_encrypted = current_keys

    return {"message": f"Exchange keys for {data.exchange} saved", "exchange": data.exchange}


async def _verify_bybit_key_permissions(api_key: str, secret: str, passphrase: str | None, key_data: dict) -> None:
    """Fail-closed permission gate: keys carrying withdrawal/transfer rights
    are rejected, and unverifiable keys are not saved at all."""
    from app.services.trading.bybit import make_client
    from app.services.trading.key_permissions import (
        check_permissions,
        fetch_bybit_key_permissions,
    )

    exchange = make_client(api_key, secret, passphrase)
    try:
        await exchange.load_markets()
        groups = await fetch_bybit_key_permissions(exchange)
    except Exception as e:
        logger.error("Bybit key permission verification failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify Bybit key permissions — keys were not saved.",
        )
    finally:
        try:
            await exchange.close()
        except Exception:
            pass

    problems = check_permissions(groups)
    if problems:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bybit key rejected: " + "; ".join(problems),
        )

    key_data["permissions_verified"] = True
    key_data["permissions_verified_at"] = datetime.now(timezone.utc).isoformat()
    key_data["permissions"] = groups


@router.get("/me/exchange-keys", response_model=list[ExchangeKeyResponse])
async def list_exchange_keys(current_user: CurrentUser):
    if not current_user.exchange_keys_encrypted:
        return []

    result = []
    for ex, data in current_user.exchange_keys_encrypted.items():
        api_key = decrypt_api_key(data.get("api_key", ""))
        masked = api_key[:4] + "****" + api_key[-4:] if len(api_key) >= 8 else "****"
        result.append(
            ExchangeKeyResponse(
                exchange=ex,
                api_key_masked=masked,
                has_passphrase="passphrase" in data,
                created_at=current_user.updated_at,
            )
        )
    return result


@router.delete("/me/exchange-keys/{exchange}")
async def delete_exchange_keys(
    exchange: str,
    current_user: CurrentUser,
):
    current_keys = dict(current_user.exchange_keys_encrypted or {})
    ex = exchange.lower()

    if ex not in current_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No keys found for exchange: {exchange}",
        )

    del current_keys[ex]
    current_user.exchange_keys_encrypted = current_keys if current_keys else None

    return {"message": f"Exchange keys for {exchange} removed"}
