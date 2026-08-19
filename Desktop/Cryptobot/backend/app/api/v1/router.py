from fastapi import APIRouter

from app.api.v1 import admin, analytics, auth, invest, market, payments, portfolio, prop_firm, signals, users

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(payments.router, prefix="/payments", tags=["payments"])
api_router.include_router(portfolio.router, prefix="/portfolios", tags=["portfolios"])
api_router.include_router(prop_firm.router, prefix="/prop-firm", tags=["prop-firm"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(signals.router, prefix="/trading", tags=["trading"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(invest.router, prefix="/invest", tags=["invest"])
