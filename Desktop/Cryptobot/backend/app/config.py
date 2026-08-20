import os
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    PROJECT_NAME: str = "TBX Trade Terminal"
    VERSION: str = "1.0.0"
    DEBUG: bool = False

    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    DATABASE_URL: str = "postgresql+asyncpg://tbx:tbx@localhost:5432/tbx"
    DATABASE_URL_SYNC: str = "postgresql://tbx:tbx@localhost:5432/tbx"

    REDIS_URL: str = "redis://localhost:6379/0"

    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    TELEGRAM_TOKEN: str = ""
    BOT_USERNAME: str = ""
    # public channel/chat for signal showcase, e.g. "-1001234567890" or "@tbx_signals";
    # the bot must be an admin of the channel
    TELEGRAM_SIGNALS_CHANNEL_ID: str = ""

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-v4-pro"
    DEEPSEEK_REASONING_MODEL: str = "deepseek-v4-pro"

    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_ENABLED: bool = False

    ENCRYPTION_KEY: str = ""

    # Bybit execution (USDT-M perpetual futures)
    BYBIT_TESTNET: bool = False
    BYBIT_LEVERAGE: int = 1
    BYBIT_MARGIN_MODE: str = "cross"  # "cross" | "isolated"

    # liquidity gate: publish signals only for pairs with >= this 24h quote
    # volume (USDT) on Binance (owner decision 2026-08-20)
    MIN_DAILY_VOLUME_USD: int = 300_000_000

    # extra high-impact macro events, JSON list: [{"name": "US CPI", "at": "2026-08-12T12:30:00+00:00"}]
    MACRO_EVENTS_JSON: str = ""

    PORT: int = int(os.getenv("PORT", "8000"))

    # Admin
    ADMIN_IDS: List[int] = [407721399]

    model_config = {
        "env_file": str(BASE_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }


settings = Settings()
