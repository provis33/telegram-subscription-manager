from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from dotenv import load_dotenv

from database import Database
from handlers import router
from scheduler import setup_scheduler

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    remind_days_before: int


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing env var: TELEGRAM_BOT_TOKEN")
    raw_days = os.getenv("REMIND_DAYS_BEFORE", "2")
    try:
        days = int(raw_days)
    except ValueError:
        days = 2
    if days < 0:
        days = 2
    return Settings(telegram_bot_token=token, remind_days_before=days)


def setup_logging() -> None:
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)


async def run() -> None:
    setup_logging()
    settings = load_settings()

    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher(storage=MemoryStorage())
    db = Database(Path("data/bot.db"))

    dp["db"] = db
    dp.include_router(router)

    scheduler = setup_scheduler(bot, db, settings.remind_days_before)

    async def on_startup() -> None:
        await db.connect()
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Регистрация"),
                BotCommand(command="add", description="Добавить подписку"),
                BotCommand(command="list", description="Список подписок"),
                BotCommand(command="cancel", description="Отменить подписку по id"),
            ]
        )
        scheduler.start()
        logger.info(
            "Bot started, remind_days_before=%s",
            settings.remind_days_before,
        )

    async def on_shutdown() -> None:
        scheduler.shutdown(wait=False)
        await db.close()
        logger.info("Bot stopped")

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
