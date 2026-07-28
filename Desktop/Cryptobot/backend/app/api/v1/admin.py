from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentAdmin, DbSession
from app.models.user import User, UserRole
from app.schemas.user import AdminStatsResponse, AdminUserUpdate, UserListResponse, UserProfileResponse

router = APIRouter()


def _user_to_profile(user: User) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(user.id),
        telegram_id=user.telegram_id,
        username=user.username,
        email=user.email,
        email_verified=user.email_verified,
        role=user.role.value,
        is_active=user.is_active,
        has_exchange_keys=user.exchange_keys_encrypted is not None,
        avatar_url=user.avatar_url,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


@router.get("/users", response_model=UserListResponse)
async def list_users(
    db: DbSession,
    _admin: CurrentAdmin,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    search: str | None = Query(default=None),
):
    offset = (page - 1) * page_size

    base_query = select(User)
    count_query = select(func.count(User.id))

    if search:
        search_filter = User.email.ilike(f"%{search}%") | User.username.ilike(f"%{search}%")
        base_query = base_query.where(search_filter)
        count_query = count_query.where(search_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    result = await db.execute(
        base_query.order_by(User.created_at.desc()).offset(offset).limit(page_size)
    )
    users = result.scalars().all()

    return UserListResponse(
        users=[_user_to_profile(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/users/{user_id}", response_model=UserProfileResponse)
async def get_user(
    user_id: UUID,
    db: DbSession,
    _admin: CurrentAdmin,
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_to_profile(user)


@router.patch("/users/{user_id}", response_model=UserProfileResponse)
async def update_user(
    user_id: UUID,
    data: AdminUserUpdate,
    db: DbSession,
    _admin: CurrentAdmin,
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if data.role is not None:
        user.role = UserRole(data.role)
    if data.is_active is not None:
        user.is_active = data.is_active

    return _user_to_profile(user)


@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(
    db: DbSession,
    _admin: CurrentAdmin,
):
    total = await db.execute(select(func.count(User.id)))
    active = await db.execute(select(func.count(User.id)).where(User.is_active == True))
    admins = await db.execute(select(func.count(User.id)).where(User.role == UserRole.ADMIN))
    verified = await db.execute(select(func.count(User.id)).where(User.email_verified == True))
    with_keys = await db.execute(select(func.count(User.id)).where(User.exchange_keys_encrypted.isnot(None)))

    return AdminStatsResponse(
        total_users=total.scalar() or 0,
        active_users=active.scalar() or 0,
        admin_users=admins.scalar() or 0,
        email_verified_users=verified.scalar() or 0,
        users_with_exchange_keys=with_keys.scalar() or 0,
    )
