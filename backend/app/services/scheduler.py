"""Фоновые задачи: опрос нод (скорость), проверки IP после падения скорости, сводка, очистка."""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import delete

from app.core import integrations
from app.core.database import SessionLocal
from app.core.timeutils import local_tz, utcnow
from app.models import Event, UserSession
from app.services import investigation_service, settings_service
from app.services.node_service import poll_nodes
from app.services.summary import send_summary

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._wake_investigations = asyncio.Event()
        self._wake_nodes = asyncio.Event()
        self.next_node_poll: float | None = None

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._investigations_loop(), name="investigations"),
            asyncio.create_task(self._summary_loop(), name="summary"),
        ]
        self._tasks.append(asyncio.create_task(self._nodes_loop(), name="nodes"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def wake(self) -> None:
        """Пересчитать расписание (после изменения настроек)."""
        self._wake_nodes.set()

    async def _sleep_or_wake(self, event: asyncio.Event, seconds: float) -> bool:
        """True — разбудили досрочно."""
        event.clear()
        try:
            await asyncio.wait_for(event.wait(), timeout=max(seconds, 1))
            return True
        except asyncio.TimeoutError:
            return False

    async def _investigations_loop(self) -> None:
        """Проверки IP после падения скорости нод (по расписанию каждой проверки)."""
        await asyncio.sleep(10)
        while True:
            try:
                await investigation_service.tick()
            except Exception:  # noqa: BLE001
                log.exception("Ошибка проверок после падения скорости")
            await self._sleep_or_wake(self._wake_investigations, 20)

    def wake_investigations(self) -> None:
        self._wake_investigations.set()

    async def _nodes_loop(self) -> None:
        await asyncio.sleep(2)
        last_run = 0.0
        while True:
            async with SessionLocal() as db:
                interval = int(await settings_service.get(db, "node_poll_interval_seconds"))
            due = last_run + interval
            if time.time() >= due and integrations.remnawave_configured():
                try:
                    await poll_nodes()
                except Exception:  # noqa: BLE001
                    log.exception("Ошибка опроса нод")
                last_run = time.time()
                due = last_run + interval
            self.next_node_poll = due
            await self._sleep_or_wake(self._wake_nodes, due - time.time())

    async def _summary_loop(self) -> None:
        while True:
            try:
                await self._summary_tick()
            except Exception:  # noqa: BLE001
                log.exception("Ошибка ежедневной сводки/очистки")
            await asyncio.sleep(30)

    async def _summary_tick(self) -> None:
        now_local = datetime.now(local_tz())
        today = now_local.date().isoformat()
        async with SessionLocal() as db:
            cfg = await settings_service.get_all(db)

            # очистка раз в сутки
            if await settings_service.get_state(db, "last_cleanup") != today:
                keep = int(cfg["events_retention_days"])
                await db.execute(delete(Event).where(Event.created_at < utcnow() - timedelta(days=keep)))
                await db.execute(delete(UserSession).where(UserSession.expires_at < utcnow()))
                await settings_service.set_state(db, "last_cleanup", today)
                await db.commit()

            if not cfg["daily_summary_enabled"]:
                return
            hh, mm = (int(x) for x in str(cfg["daily_summary_time"]).split(":"))
            if (now_local.hour, now_local.minute) < (hh, mm):
                return
            if await settings_service.get_state(db, "last_summary_date") == today:
                return
            await settings_service.set_state(db, "last_summary_date", today)
            await db.commit()
            await send_summary(db)


scheduler = Scheduler()
