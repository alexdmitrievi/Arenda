from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.portfolio import ChallengeStatus, PropFirmChallenge
from app.services.prop_firm.engine import (
    get_firm_rules,
    check_daily_loss,
    check_trailing_dd,
    check_profit_target,
    update_challenge_progress,
)

router = APIRouter()


class ChallengeCreate(BaseModel):
    firm: str = Field(min_length=1, max_length=64)
    account_size: float = Field(gt=0)


class ChallengeProgressUpdate(BaseModel):
    current_equity: float
    daily_pnl: float = 0.0
    trading_day: int = Field(ge=1)


class FirmRulesResponse(BaseModel):
    firm: str
    name: str
    max_daily_loss_pct: float
    max_trailing_dd_pct: float
    profit_target_pct: float
    min_trading_days: int
    max_position_risk_pct: float
    account_sizes: list[int]
    price_usd: dict[int, int]


@router.get("/firms")
async def list_firms():
    from app.services.prop_firm.engine import PROP_FIRM_RULES
    return [
        FirmRulesResponse(
            firm=key,
            name=data["name"],
            max_daily_loss_pct=data["max_daily_loss_pct"],
            max_trailing_dd_pct=data["max_trailing_dd_pct"],
            profit_target_pct=data["profit_target_pct"],
            min_trading_days=data["min_trading_days"],
            max_position_risk_pct=data["max_position_risk_pct"],
            account_sizes=data["account_sizes"],
            price_usd=data["price_usd"],
        )
        for key, data in PROP_FIRM_RULES.items()
    ]


@router.post("/challenges", status_code=status.HTTP_201_CREATED)
async def start_challenge(data: ChallengeCreate, current_user: CurrentUser, db: DbSession):
    rules = get_firm_rules(data.firm)
    if not rules:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown firm: {data.firm}")

    account_size = Decimal(str(data.account_size))
    if int(account_size) not in rules["account_sizes"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid account size. Available: {rules['account_sizes']}",
        )

    challenge = PropFirmChallenge(
        user_id=current_user.id,
        firm=data.firm,
        account_size=account_size,
        rules={
            "max_daily_loss_pct": rules["max_daily_loss_pct"],
            "max_trailing_dd_pct": rules["max_trailing_dd_pct"],
            "profit_target_pct": rules["profit_target_pct"],
            "min_trading_days": rules["min_trading_days"],
            "max_position_risk_pct": rules["max_position_risk_pct"],
        },
        progress={
            "starting_equity": float(account_size),
            "current_equity": float(account_size),
            "peak_equity": float(account_size),
            "daily_pnl": 0,
            "trading_days_completed": 0,
        },
        status=ChallengeStatus.ACTIVE,
        started_at=datetime.now(timezone.utc),
    )
    db.add(challenge)
    await db.flush()

    return {
        "id": str(challenge.id),
        "firm": challenge.firm,
        "account_size": float(challenge.account_size),
        "status": challenge.status.value,
        "rules": challenge.rules,
        "progress": challenge.progress,
    }


@router.get("/challenges")
async def list_challenges(current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(PropFirmChallenge)
        .where(PropFirmChallenge.user_id == current_user.id)
        .order_by(PropFirmChallenge.created_at.desc())
    )
    challenges = result.scalars().all()
    return [
        {
            "id": str(c.id), "firm": c.firm, "account_size": float(c.account_size),
            "status": c.status.value, "rules": c.rules, "progress": c.progress,
            "started_at": c.started_at.isoformat() if c.started_at else None,
        }
        for c in challenges
    ]


@router.get("/challenges/{challenge_id}/progress")
async def get_challenge_progress(challenge_id: UUID, current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(PropFirmChallenge).where(
            PropFirmChallenge.id == challenge_id, PropFirmChallenge.user_id == current_user.id
        )
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    progress = challenge.progress or {}
    rules = challenge.rules or {}

    return {
        "firm": challenge.firm,
        "account_size": float(challenge.account_size),
        "status": challenge.status.value,
        "daily_loss": check_daily_loss(progress, rules),
        "trailing_dd": check_trailing_dd(progress, rules),
        "profit_target": check_profit_target(progress, rules),
        "trading_days": {
            "current": progress.get("trading_days_completed", 0),
            "required": rules.get("min_trading_days", 5),
        },
        "equity": {
            "starting": progress.get("starting_equity", 0),
            "current": progress.get("current_equity", 0),
            "peak": progress.get("peak_equity", 0),
        },
    }


@router.post("/challenges/{challenge_id}/progress")
async def update_challenge_progress_endpoint(
    challenge_id: UUID,
    data: ChallengeProgressUpdate,
    current_user: CurrentUser,
    db: DbSession,
):
    result = await db.execute(
        select(PropFirmChallenge).where(
            PropFirmChallenge.id == challenge_id, PropFirmChallenge.user_id == current_user.id
        )
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    if challenge.status not in (ChallengeStatus.ACTIVE, ChallengeStatus.PAUSED):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Challenge is not active")

    status_data = update_challenge_progress(
        challenge, data.current_equity, data.daily_pnl, data.trading_day
    )

    return status_data


@router.post("/challenges/{challenge_id}/pause")
async def pause_challenge(challenge_id: UUID, current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(PropFirmChallenge).where(
            PropFirmChallenge.id == challenge_id, PropFirmChallenge.user_id == current_user.id
        )
    )
    challenge = result.scalar_one_or_none()
    if not challenge:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Challenge not found")

    challenge.status = ChallengeStatus.PAUSED
    return {"status": challenge.status.value}
