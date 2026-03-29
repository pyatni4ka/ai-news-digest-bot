from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from digest_bot.service import DigestService


class DigestScheduler:
    def __init__(self, service: DigestService) -> None:
        self._service = service
        self._scheduler = AsyncIOScheduler(timezone=service.settings.timezone)

    def start(self) -> None:
        self._scheduler.add_job(
            self._service.run_scheduled_digest,
            CronTrigger(hour=self._service.settings.morning_hour, minute=0),
            kwargs={"slot": "morning"},
            id="morning-digest",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._service.run_scheduled_digest,
            CronTrigger(hour=self._service.settings.evening_hour, minute=0),
            kwargs={"slot": "evening"},
            id="evening-digest",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._service.run_scheduled_digest,
            CronTrigger(day_of_week="sun", hour=self._service.settings.morning_hour, minute=30),
            kwargs={"slot": "weekly"},
            id="weekly-digest",
            replace_existing=True,
        )
        self._scheduler.start()

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)
