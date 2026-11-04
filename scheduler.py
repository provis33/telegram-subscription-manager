from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import Database
from handlers.subscriptions import action_keyboard, format_sub

logger = logging.getLogger(__name__)


def setup_scheduler(bot: Bot, db: Database, remind_days_before: int) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def remind_job() -> None:
        # дата по UTC, т.к. джоба в 10:00 UTC / use UTC date to match cron
        target = datetime.now(timezone.utc).date() + timedelta(days=remind_days_before)
        rows = await db.due_for_reminder(target)
        logger.info("Reminder job: target=%s, found=%s", target, len(rows))
        for tg_id, sub in rows:
            try:
                await bot.send_message(
                    tg_id,
                    f"⏰ Напоминание: через {remind_days_before} дн. списание\n\n"
                    f"{format_sub(sub)}",
                    parse_mode="HTML",
                    reply_markup=action_keyboard(sub.id),
                )
            except Exception:
                logger.exception("Failed to remind tg_id=%s sub=%s", tg_id, sub.id)

    # каждый день в 10:00 UTC / daily at 10:00 UTC
    scheduler.add_job(remind_job, CronTrigger(hour=10, minute=0), id="daily_reminders")
    return scheduler
