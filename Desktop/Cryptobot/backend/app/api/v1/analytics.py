from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.services.analytics.performance import get_overview_stats, get_pnl_report, get_user_metrics

router = APIRouter()


@router.get("/overview")
async def analytics_overview():
    stats = await get_overview_stats()
    return stats


@router.get("/pnl")
async def pnl_report(
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
):
    return await get_pnl_report(str(current_user.id), days)


@router.get("/metrics")
async def user_metrics_endpoint(current_user: CurrentUser):
    return await get_user_metrics(str(current_user.id))
