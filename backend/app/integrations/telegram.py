"""Отправка уведомлений в Telegram (только исходящие сообщения)."""
import html
import logging

import httpx

from app.core import integrations
from app.core.config import get_settings
from app.core.http import get_http

log = logging.getLogger(__name__)


class TelegramError(Exception):
    pass


def esc(text: object) -> str:
    return html.escape(str(text), quote=False)


async def send_message(text: str, client: httpx.AsyncClient | None = None) -> None:
    s = get_settings()
    if not integrations.telegram_configured():
        raise TelegramError("Telegram не настроен: укажите токен бота и chat id в Настройках")
    client = client or get_http()
    url = f"{s.telegram_api_url.rstrip('/')}/bot{integrations.get('telegram_bot_token')}/sendMessage"
    try:
        resp = await client.post(
            url,
            json={
                "chat_id": integrations.get("telegram_chat_id"),
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except httpx.HTTPError as e:
        raise TelegramError(f"Сетевая ошибка Telegram: {e}") from e
    if resp.status_code != 200:
        raise TelegramError(f"Telegram HTTP {resp.status_code}: {resp.text[:200]}")
