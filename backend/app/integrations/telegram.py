"""Отправка уведомлений в Telegram (только исходящие сообщения)."""
import html
import re
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


def chat_ids() -> list[str]:
    """Все получатели: chat id через запятую, пробел или с новой строки."""
    raw = integrations.get("telegram_chat_id")
    ids: list[str] = []
    for part in re.split(r"[,;\s]+", raw or ""):
        part = part.strip()
        if part and part not in ids:
            ids.append(part)
    return ids


async def _send_one(client: httpx.AsyncClient, url: str, chat_id: str, text: str) -> str | None:
    """Отправляет одному получателю. Возвращает текст ошибки или None."""
    try:
        resp = await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except httpx.HTTPError as e:
        return f"сетевая ошибка: {e}"
    if resp.status_code != 200:
        try:
            desc = resp.json().get("description", "")
        except ValueError:
            desc = resp.text[:200]
        return f"HTTP {resp.status_code}: {desc}"
    return None


async def send_message(text: str, client: httpx.AsyncClient | None = None) -> int:
    """Отправляет сообщение всем получателям. Возвращает, скольким дошло.

    Если хоть одному не дошло — TelegramError с подробностями (остальным всё равно отправлено).
    """
    s = get_settings()
    ids = chat_ids()
    if not integrations.get("telegram_bot_token") or not ids:
        raise TelegramError("Telegram не настроен: укажите токен бота и chat id в Настройках")
    client = client or get_http()
    url = f"{s.telegram_api_url.rstrip('/')}/bot{integrations.get('telegram_bot_token')}/sendMessage"

    failed = []
    for chat_id in ids:
        err = await _send_one(client, url, chat_id, text)
        if err:
            failed.append(f"{chat_id}: {err}")
            log.warning("Telegram %s: %s", chat_id, err)
    if failed:
        raise TelegramError(f"Доставлено {len(ids) - len(failed)} из {len(ids)}. Ошибки — " + "; ".join(failed))
    return len(ids)
