from __future__ import annotations
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import get_settings
from bot.handlers import router as bot_router
from app.logging_config import setup_logging
import structlog


setup_logging()
logger = structlog.get_logger(__name__)


async def main() -> None:
	settings = get_settings()
	if not settings.telegram_bot_token:
		raise RuntimeError("TELEGRAM_BOT_TOKEN is not set in environment")

	bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=None))
	dp = Dispatcher()
	dp.include_router(bot_router)

	await bot.delete_webhook(drop_pending_updates=True)
	logger.info("bot_starting", mode="polling")
	await dp.start_polling(bot)


if __name__ == "__main__":
	asyncio.run(main())