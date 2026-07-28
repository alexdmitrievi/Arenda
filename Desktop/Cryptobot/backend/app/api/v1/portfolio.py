from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models.portfolio import (
    DCAFrequency,
    DCAPlan,
    Portfolio,
    PortfolioType,
    PORTFOLIO_TEMPLATES,
    RebalanceFrequency,
)
from app.services.portfolio.dca import calculate_dynamic_steps, get_next_execution
from app.services.portfolio.rebalancer import calculate_rebalance_trades, should_rebalance

router = APIRouter()


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: PortfolioType = PortfolioType.CUSTOM
    allocation: dict[str, float] = Field(default_factory=dict)
    rebalance_threshold_pct: float = Field(default=5.0, ge=0.1, le=50.0)
    rebalance_frequency: RebalanceFrequency = RebalanceFrequency.MANUAL


class PortfolioResponse(BaseModel):
    id: str
    name: str
    type: str
    allocation: dict
    rebalance_threshold_pct: float
    rebalance_frequency: str
    is_active: bool
    created_at: str | None

    model_config = {"from_attributes": True}


class DCAPlanCreate(BaseModel):
    portfolio_id: str | None = None
    asset: str = Field(min_length=1, max_length=32)
    amount_per_period: float = Field(gt=0)
    frequency: DCAFrequency = DCAFrequency.WEEKLY
    atr_multiplier: float = Field(default=2.0, ge=0.5, le=5.0)


class DCAPlanResponse(BaseModel):
    id: str
    asset: str
    amount_per_period: float
    frequency: str
    atr_multiplier: float
    active_steps: dict | None
    next_execution_at: str | None
    is_active: bool
    created_at: str | None


@router.get("/templates")
async def get_portfolio_templates():
    return [
        {
            "type": t.value,
            "name": data["name"],
            "allocation": data["allocation"],
            "description": data["description"],
        }
        for t, data in PORTFOLIO_TEMPLATES.items()
    ]


@router.get("", response_model=list[PortfolioResponse])
async def list_portfolios(current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == current_user.id).order_by(Portfolio.created_at.desc())
    )
    portfolios = result.scalars().all()
    return [
        PortfolioResponse(
            id=str(p.id), name=p.name, type=p.type.value, allocation=p.allocation,
            rebalance_threshold_pct=float(p.rebalance_threshold_pct),
            rebalance_frequency=p.rebalance_frequency.value, is_active=p.is_active,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in portfolios
    ]


@router.post("", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(data: PortfolioCreate, current_user: CurrentUser, db: DbSession):
    portfolio = Portfolio(
        user_id=current_user.id,
        name=data.name,
        type=data.type,
        allocation=data.allocation,
        rebalance_threshold_pct=Decimal(str(data.rebalance_threshold_pct)),
        rebalance_frequency=data.rebalance_frequency,
    )
    db.add(portfolio)
    await db.flush()

    return PortfolioResponse(
        id=str(portfolio.id), name=portfolio.name, type=portfolio.type.value,
        allocation=portfolio.allocation,
        rebalance_threshold_pct=float(portfolio.rebalance_threshold_pct),
        rebalance_frequency=portfolio.rebalance_frequency.value,
        is_active=portfolio.is_active,
        created_at=portfolio.created_at.isoformat() if portfolio.created_at else None,
    )


@router.delete("/{portfolio_id}")
async def delete_portfolio(portfolio_id: UUID, current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id)
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")
    await db.delete(portfolio)
    return {"message": "Portfolio deleted"}


@router.post("/{portfolio_id}/rebalance")
async def rebalance_portfolio(
    portfolio_id: UUID,
    current_prices: dict[str, float],
    current_user: CurrentUser,
    db: DbSession,
):
    result = await db.execute(
        select(Portfolio).where(Portfolio.id == portfolio_id, Portfolio.user_id == current_user.id)
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    target = {k: float(v) for k, v in portfolio.allocation.items()}
    current = {
        asset: float(amt) * current_prices.get(asset, 0)
        for asset, amt in {}  # would come from actual position tracking
    }
    total_value = sum(current.values()) or 1
    current_pct = {asset: val / total_value * 100 for asset, val in current.items()}

    needs, adjustments = should_rebalance(target, current_pct, float(portfolio.rebalance_threshold_pct))
    trades = calculate_rebalance_trades(adjustments, total_value, current_prices)

    return {"needs_rebalance": needs, "adjustments": adjustments, "trades": trades}


@router.get("/dca-plans", response_model=list[DCAPlanResponse])
async def list_dca_plans(current_user: CurrentUser, db: DbSession):
    result = await db.execute(
        select(DCAPlan).where(DCAPlan.user_id == current_user.id).order_by(DCAPlan.created_at.desc())
    )
    plans = result.scalars().all()
    return [
        DCAPlanResponse(
            id=str(p.id), asset=p.asset, amount_per_period=float(p.amount_per_period),
            frequency=p.frequency.value, atr_multiplier=float(p.atr_multiplier),
            active_steps=p.active_steps,
            next_execution_at=p.next_execution_at.isoformat() if p.next_execution_at else None,
            is_active=p.is_active,
            created_at=p.created_at.isoformat() if p.created_at else None,
        )
        for p in plans
    ]


@router.post("/dca-plans", response_model=DCAPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_dca_plan(data: DCAPlanCreate, current_user: CurrentUser, db: DbSession):
    plan = DCAPlan(
        user_id=current_user.id,
        portfolio_id=UUID(data.portfolio_id) if data.portfolio_id else None,
        asset=data.asset,
        amount_per_period=Decimal(str(data.amount_per_period)),
        frequency=data.frequency,
        atr_multiplier=Decimal(str(data.atr_multiplier)),
        next_execution_at=get_next_execution(data.frequency),
    )
    db.add(plan)
    await db.flush()

    return DCAPlanResponse(
        id=str(plan.id), asset=plan.asset, amount_per_period=float(plan.amount_per_period),
        frequency=plan.frequency.value, atr_multiplier=float(plan.atr_multiplier),
        active_steps=plan.active_steps, next_execution_at=plan.next_execution_at.isoformat() if plan.next_execution_at else None,
        is_active=plan.is_active, created_at=plan.created_at.isoformat() if plan.created_at else None,
    )


@router.delete("/dca-plans/{plan_id}")
async def delete_dca_plan(plan_id: UUID, current_user: CurrentUser, db: DbSession):
    result = await db.execute(select(DCAPlan).where(DCAPlan.id == plan_id, DCAPlan.user_id == current_user.id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DCA plan not found")
    await db.delete(plan)
    return {"message": "DCA plan deleted"}
