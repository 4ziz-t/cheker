"""Настройки, редактируемые через фронт (хранятся в SQLite)."""
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checkers import default_enabled
from app.models import Setting

# Типы событий: ключ → название (для переключателей уведомлений)
EVENT_TYPES: dict[str, str] = {
    "ip_blocked": "IP попал в бан",
    "ip_unblocked": "IP разбанен",
    "ip_switched_auto": "Автоматическая смена IP",
    "ip_switched_manual": "Ручная смена IP",
    "no_available_ips": "Нет доступных IP для домена",
    "dns_changed": "A-запись изменена вне панели",
    "domain_imported": "Домен/IP ноды добавлен из Remnawave",
    "node_offline": "Нода offline",
    "node_online": "Нода снова online",
    "integration_error": "Ошибки API (Cloudflare, Remnawave, чекеры)",
    "security": "Блокировка входа (подбор пароля)",
    "daily_summary": "Ежедневная сводка",
}

DEFAULTS: dict[str, Any] = {
    "check_interval_minutes": 60,
    "node_poll_interval_seconds": 60,
    "auto_switch_enabled": True,
    "checker_delay_ms": 1000,
    "enabled_checkers": None,  # None → берём default_enabled() из реестра
    "daily_summary_enabled": True,
    "daily_summary_time": "10:00",
    "notify": {k: True for k in EVENT_TYPES},
    "events_retention_days": 90,
    "auto_import_nodes": True,
    "check_reserve_ips": False,
    "latencylab_throttle_is_ban": True,
    "latencylab_mode": "auto",
    "latencylab_fail_percent": 50,
    "tcp_check_port": 443,
    "geopinger_places": ["Москва", "Санкт-Петербург", "Екатеринбург", "Новосибирск", "Казань"],
    "geopinger_control_places": [],
    "geopinger_fail_percent": 50,
}

# служебное состояние (не показывается как настройка)
STATE_PREFIX = "state."


async def _get_raw(db: AsyncSession, key: str) -> Any:
    row = await db.get(Setting, key)
    return json.loads(row.value) if row else None


async def _set_raw(db: AsyncSession, key: str, value: Any) -> None:
    row = await db.get(Setting, key)
    data = json.dumps(value, ensure_ascii=False)
    if row:
        row.value = data
    else:
        db.add(Setting(key=key, value=data))


async def get_all(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(select(Setting).where(~Setting.key.startswith(STATE_PREFIX)))).scalars().all()
    stored = {r.key: json.loads(r.value) for r in rows}
    result = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
    # дополняем notify новыми типами событий
    result["notify"] = {**DEFAULTS["notify"], **(result.get("notify") or {})}
    if result["enabled_checkers"] is None:
        result["enabled_checkers"] = default_enabled()
    return result


async def get(db: AsyncSession, key: str) -> Any:
    return (await get_all(db))[key]


async def update(db: AsyncSession, patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if key in DEFAULTS and value is not None:
            await _set_raw(db, key, value)
    await db.commit()
    return await get_all(db)


async def get_state(db: AsyncSession, key: str, default: Any = None) -> Any:
    v = await _get_raw(db, STATE_PREFIX + key)
    return default if v is None else v


async def set_state(db: AsyncSession, key: str, value: Any) -> None:
    await _set_raw(db, STATE_PREFIX + key, value)


async def migrate(db: AsyncSession) -> None:
    """Разовые изменения настроек при обновлении версии."""
    # Latency Lab стал основным источником — включаем его один раз и у тех,
    # кто уже сохранял список источников.
    if not await get_state(db, "migrated_latencylab"):
        row = await db.get(Setting, "enabled_checkers")
        if row:
            current = json.loads(row.value) or []
            if "latencylab" not in current:
                row.value = json.dumps(["latencylab", *current])
        await set_state(db, "migrated_latencylab", True)
        await db.commit()
