from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UserProfileResponse(BaseModel):
    id: str
    telegram_id: int | None
    username: str | None
    email: str | None
    email_verified: bool
    role: str
    is_active: bool
    has_exchange_keys: bool
    avatar_url: str | None
    last_login_at: datetime | None
    created_at: datetime | None

    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    username: str | None = Field(default=None, max_length=128)
    email: str | None = None
    avatar_url: str | None = None


class UserRegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=128)
    username: str | None = Field(default=None, max_length=128)


class UserLoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class TelegramAuthRequest(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class ExchangeKeySet(BaseModel):
    exchange: str = Field(min_length=1, max_length=32)
    api_key: str = Field(min_length=1)
    secret: str = Field(min_length=1)
    passphrase: str | None = None


class ExchangeKeyResponse(BaseModel):
    exchange: str
    api_key_masked: str
    has_passphrase: bool
    created_at: datetime | None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class AdminUserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    is_active: bool | None = None


class UserListResponse(BaseModel):
    users: list[UserProfileResponse]
    total: int
    page: int
    page_size: int


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    admin_users: int
    email_verified_users: int
    users_with_exchange_keys: int
