import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger("tbx.ai")

_client: AsyncOpenAI | None = None


def get_deepseek_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )
        logger.info("DeepSeek client initialized: %s", settings.DEEPSEEK_BASE_URL)
    return _client
