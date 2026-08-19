import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.redis import rate_limit_check
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import (
    ForgotPasswordRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TelegramAuthRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
)

router = APIRouter()

TELEGRAM_TOKEN_HASH: bytes | None = None


def set_telegram_token(token: str) -> None:
    global TELEGRAM_TOKEN_HASH
    if token:
        TELEGRAM_TOKEN_HASH = hashlib.sha256(token.encode()).digest()


def _check_telegram_auth(request: TelegramAuthRequest) -> bool:
    if TELEGRAM_TOKEN_HASH is None:
        return False
    current_time = int(time.time())
    if abs(current_time - request.auth_date) > 86400:
        return False
    data_check_string = "\n".join(
        f"{k}={v}"
        for k, v in sorted(
            {
                "id": request.id,
                "first_name": request.first_name or "",
                "last_name": request.last_name or "",
                "username": request.username or "",
                "photo_url": request.photo_url or "",
                "auth_date": request.auth_date,
            }.items()
        )
        if v
    )
    expected_hash = hmac.new(
        TELEGRAM_TOKEN_HASH,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_hash, request.hash)


async def _send_verification_email(user: User) -> None:
    pass


RESET_TOKEN_TTL = timedelta(hours=1)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def _enforce_rate_limit(request: Request, action: str, identifier: str = ""):
    ip = _client_ip(request)
    if not await rate_limit_check(f"{action}:{ip}:{identifier}", max_attempts=5, window_seconds=900):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again in 15 minutes.",
        )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: UserRegisterRequest,
    http_request: Request,
    db: DbSession,
):
    await _enforce_rate_limit(http_request, "register")

    existing = await db.execute(select(User).where(User.email == request.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        username=request.username or request.email.split("@")[0],
        email_verification_token=secrets.token_urlsafe(32),
        email_verification_sent_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    # 7-day full trial auto-starts at registration: the first session must
    # show live signals, not a paywall
    from app.models.subscription import Subscription, SubscriptionPlan, SubscriptionStatus
    db.add(Subscription(
        user_id=user.id,
        plan=SubscriptionPlan.TRADER,
        status=SubscriptionStatus.TRIAL,
        started_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        trial_used=True,
    ))

    user_id_str = str(user.id)
    access_token = create_access_token({"sub": user_id_str})
    refresh_token = create_refresh_token({"sub": user_id_str})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    request: UserLoginRequest,
    http_request: Request,
    db: DbSession,
):
    await _enforce_rate_limit(http_request, "login", request.email.lower())

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is None or user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    user.last_login_at = datetime.now(timezone.utc)

    user_id_str = str(user.id)
    access_token = create_access_token({"sub": user_id_str})
    refresh_token = create_refresh_token({"sub": user_id_str})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/telegram", response_model=TokenResponse)
async def telegram_auth(
    request: TelegramAuthRequest,
    db: DbSession,
):
    if not _check_telegram_auth(request):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Telegram authentication data",
        )

    result = await db.execute(
        select(User).where(User.telegram_id == request.id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(
            telegram_id=request.id,
            username=request.username,
            avatar_url=request.photo_url,
        )
        db.add(user)
        await db.flush()
    else:
        if request.username:
            user.username = request.username
        if request.photo_url:
            user.avatar_url = request.photo_url
        user.last_login_at = datetime.now(timezone.utc)

    user_id_str = str(user.id)
    access_token = create_access_token({"sub": user_id_str})
    refresh_token = create_refresh_token({"sub": user_id_str})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_access_token(
    request: RefreshRequest,
    db: DbSession,
):
    try:
        payload = decode_token(request.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = payload.get("sub")
    user_uuid = UUID(user_id)
    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    access_token = create_access_token({"sub": user_id})
    new_refresh_token = create_refresh_token({"sub": user_id})

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
    )


@router.get("/verify-email/{token}")
async def verify_email(
    token: str,
    db: DbSession,
):
    result = await db.execute(
        select(User).where(User.email_verification_token == token)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid verification token",
        )

    user.email_verified = True
    user.email_verification_token = None

    return {"message": "Email verified successfully"}


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    http_request: Request,
    db: DbSession,
):
    await _enforce_rate_limit(http_request, "forgot")

    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if user is not None:
        user.email_verification_token = secrets.token_urlsafe(32)
        user.email_verification_sent_at = datetime.now(timezone.utc)

    return {"message": "If the email is registered, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest,
    db: DbSession,
):
    result = await db.execute(
        select(User).where(User.email_verification_token == request.token)
    )
    user = result.scalar_one_or_none()

    token_expired = (
        user is not None
        and user.email_verification_sent_at is not None
        and datetime.now(timezone.utc) - user.email_verification_sent_at > RESET_TOKEN_TTL
    )
    if user is None or token_expired:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired reset token",
        )

    user.password_hash = hash_password(request.new_password)
    user.email_verification_token = None

    return {"message": "Password reset successfully"}


@router.post("/logout")
async def logout(current_user: CurrentUser):
    return {"message": "Logged out. Please discard the tokens client-side."}
