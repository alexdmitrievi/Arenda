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
    current_keys = current_user.exchange_keys_encrypted or {}

    key_data = {
        "api_key": encrypt_api_key(data.api_key),
        "secret": encrypt_api_key(data.secret),
    }
    if data.passphrase:
        key_data["passphrase"] = encrypt_api_key(data.passphrase)

    current_keys[data.exchange.lower()] = key_data
    current_user.exchange_keys_encrypted = current_keys

    return {"message": f"Exchange keys for {data.exchange} saved", "exchange": data.exchange}


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
    current_keys = current_user.exchange_keys_encrypted or {}
    ex = exchange.lower()

    if ex not in current_keys:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No keys found for exchange: {exchange}",
        )

    del current_keys[ex]
    current_user.exchange_keys_encrypted = current_keys if current_keys else None

    return {"message": f"Exchange keys for {exchange} removed"}
