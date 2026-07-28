import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.database import engine
from app.core.redis import init_redis, close_redis
from app.api.v1.router import api_router
from app.api.v1.auth import set_telegram_token
from app.bot.bot import start_bot, stop_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tbx")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("TBX Trade Terminal starting...")

    await init_redis()

    if settings.TELEGRAM_TOKEN:
        set_telegram_token(settings.TELEGRAM_TOKEN)
        await start_bot()
        logger.info("Telegram bot integrated")

    yield

    if settings.TELEGRAM_TOKEN:
        await stop_bot()

    await close_redis()
    await engine.dispose()
    logger.info("TBX Trade Terminal shutting down...")


def create_application() -> FastAPI:
    application = FastAPI(
        title="TBX Trade Terminal",
        description="Trading & Investment Platform API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(api_router, prefix="/api/v1")

    @application.get("/api/health")
    async def health_check():
        return JSONResponse({"status": "ok", "version": "1.0.0"})

    @application.get("/")
    async def root():
        return JSONResponse({"service": "TBX Trade Terminal", "version": "1.0.0"})

    return application


app = create_application()
