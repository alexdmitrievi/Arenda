import logging

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.config import settings
from app.services.market_context.engine import (
    load_context,
    macro_blackout,
    scheduled_macro_events,
)

logger = logging.getLogger("tbx.api.market")

router = APIRouter()


@router.get("/context")
async def get_market_context(current_user: CurrentUser):
    """Current market regime snapshot: BTC bias, altseason score, cycle phase,
    equity risk appetite and macro-blackout state."""
    context = await load_context() or {}
    context["macro_blackout"] = macro_blackout(extra_events_json=settings.MACRO_EVENTS_JSON)
    return context


@router.get("/macro-events")
async def get_macro_events(current_user: CurrentUser, limit: int = 10):
    """Upcoming scheduled high-impact releases the robot pauses around."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    events = [e for e in scheduled_macro_events(settings.MACRO_EVENTS_JSON) if e["at"] > now]
    return {"events": events[:limit]}
