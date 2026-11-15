"""Журнал событий + отправка уведомлений в Telegram."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations import telegram
from app.integrations.telegram import esc
from app.models import Event
from app.services import settings_service

log = logging.getLogger(__name__)

LEVEL_EMOJI = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "🚨"}


async def record(
    db: AsyncSession,
    type: str,
    title: str,
    message: str = "",
    *,
    level: str = "info",
    domain: str | None = None,
    node: str | None = None,
    ip: str | None = None,
    emoji: str | None = None,
    tg_text: str | None = None,
    notify: bool = True,
) -> Event:
    ev = Event(type=type, level=level, title=title, message=message, domain=domain, node=node, ip=ip)
    db.add(ev)
    await db.commit()

    if notify:
        notify_map = await settings_service.get(db, "notify")
        if notify_map.get(type, False):
            text = tg_text or f"{emoji or LEVEL_EMOJI.get(level, '')} <b>{esc(title)}</b>\n{esc(message)}".strip()
            try:
                await telegram.send_message(text)
            except telegram.TelegramError as e:
                log.warning("Не удалось отправить уведомление: %s", e)
    return ev


class ErrorTracker:
    """Не спамит одинаковыми ошибками: уведомляет при появлении и при восстановлении."""

    def __init__(self) -> None:
        self.active: dict[str, str] = {}

    async def report(self, db: AsyncSession, key: str, source: str, error: str) -> None:
        log.warning("[%s] %s", key, error)
        if key in self.active:
            self.active[key] = error
            return
        self.active[key] = error
        await record(db, "integration_error", f"Ошибка: {source}", error, level="error")

    async def resolve(self, db: AsyncSession, key: str, source: str) -> None:
        if self.active.pop(key, None) is not None:
            await record(db, "integration_error", f"Восстановлено: {source}", "Сервис снова отвечает", level="success")


errors = ErrorTracker()
