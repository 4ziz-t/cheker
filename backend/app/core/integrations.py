"""Настройки интеграций (токены, URL), редактируемые из фронта.

Значение из БД имеет приоритет; если в БД пусто — берётся значение из .env.
Хранятся в памяти процесса, чтобы клиенты API могли читать их синхронно;
перечитываются при старте и после каждого изменения из панели.
"""
import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings


@dataclass(frozen=True)
class Field:
    key: str
    title: str
    group: str
    secret: bool = True
    hint: str = ""


FIELDS: list[Field] = [
    Field("remnawave_url", "URL панели", "remnawave", secret=False, hint="https://panel.example.com"),
    Field("remnawave_token", "API-токен", "remnawave", hint="Панель → Настройки → API Tokens"),
    Field("remnawave_api_key", "X-Api-Key (необязательно)", "remnawave",
          hint="Только если панель закрыта доп. защитой на Caddy"),
    Field("cloudflare_api_token", "API Token", "cloudflare", hint="Права: Zone:Read + DNS:Edit"),
    Field("telegram_bot_token", "Токен бота", "telegram", hint="Выдаёт @BotFather"),
    Field("telegram_chat_id", "Chat ID", "telegram", secret=False, hint="Ваш id, можно узнать у @userinfobot"),
    Field("cheburcheck_token", "API-токен", "cheburcheck", hint="Нужен для проверки ТСПУ (пробы)"),
    Field("geopinger_token", "API-токен", "geopinger", hint="geopinger.net → Профиль → API"),
]
FIELD_MAP = {f.key: f for f in FIELDS}

GROUPS = {
    "remnawave": "Remnawave",
    "cloudflare": "Cloudflare",
    "telegram": "Telegram",
    "cheburcheck": "Cheburcheck",
    "geopinger": "GeoPinger",
}

DB_PREFIX = "integration."

_db_values: dict[str, str] = {}


def _env_value(key: str) -> str:
    return str(getattr(get_settings(), key, "") or "")


def get(key: str) -> str:
    return _db_values.get(key) or _env_value(key)


def source(key: str) -> str:
    if _db_values.get(key):
        return "panel"
    if _env_value(key):
        return "env"
    return "none"


def remnawave_configured() -> bool:
    return bool(get("remnawave_url") and get("remnawave_token"))


def cloudflare_configured() -> bool:
    return bool(get("cloudflare_api_token"))


def telegram_configured() -> bool:
    return bool(get("telegram_bot_token") and get("telegram_chat_id"))


def mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}••••{value[-4:]}"


def public_view() -> list[dict]:
    """Для фронта: секреты маскируются."""
    result = []
    for f in FIELDS:
        value = get(f.key)
        result.append({
            "key": f.key,
            "title": f.title,
            "group": f.group,
            "secret": f.secret,
            "hint": f.hint,
            "value": mask(value) if f.secret else value,
            "is_set": bool(value),
            "source": source(f.key),
        })
    return result


async def load(db: AsyncSession) -> None:
    from sqlalchemy import select

    from app.models import Setting

    rows = (await db.execute(select(Setting).where(Setting.key.startswith(DB_PREFIX)))).scalars().all()
    _db_values.clear()
    for r in rows:
        key = r.key[len(DB_PREFIX):]
        if key in FIELD_MAP:
            try:
                _db_values[key] = str(json.loads(r.value) or "")
            except ValueError:
                pass


async def update(db: AsyncSession, patch: dict[str, str | None]) -> None:
    """None — не менять; пустая строка — удалить значение из панели (вернуться к .env)."""
    from app.models import Setting

    for key, value in patch.items():
        if key not in FIELD_MAP or value is None:
            continue
        value = value.strip()
        if key == "remnawave_url":
            value = value.rstrip("/")
        row = await db.get(Setting, DB_PREFIX + key)
        if value:
            data = json.dumps(value)
            if row:
                row.value = data
            else:
                db.add(Setting(key=DB_PREFIX + key, value=data))
        elif row:
            await db.delete(row)
    await db.commit()
    await load(db)
