"""Настройки, редактируемые через фронт (хранятся в SQLite)."""
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checkers import all_checkers, default_enabled
from app.models import Setting

# Типы событий: ключ → название (для переключателей уведомлений)
EVENT_TYPES: dict[str, str] = {
    "speed_drop": "Упала скорость ноды — начата проверка IP",
    "node_suspect": "IP не в бане, но скорость ноды низкая",
    "ip_blocked": "IP в бане",
    "ip_unblocked": "IP разбанен",
    "ip_switched_auto": "Автоматическая смена IP",
    "ip_switched_manual": "Ручная смена IP",
    "no_available_ips": "Нет доступных IP для домена",
    "dns_changed": "A-запись изменена вне панели",
    "domain_imported": "Домен/IP ноды добавлен из Remnawave",
    "node_offline": "Нода offline",
    "node_online": "Нода снова online",
    "integration_error": "Ошибки API (Cloudflare, Remnawave, Red Atlas, Latency Lab, bschekbot)",
    "security": "Блокировка входа (подбор пароля)",
    "daily_summary": "Ежедневный отчёт по нодам",
}

DEFAULTS: dict[str, Any] = {
    # --- ноды и скорость ---
    "node_poll_interval_seconds": 60,
    "node_offline_confirm_polls": 2,   # «offline»/«online» — только если состояние держится N опросов подряд
    "auto_import_nodes": True,
    "speed_drop_percent": 99,          # скорость упала на X% от нормы
    "speed_window_minutes": 5,         # текущая скорость = среднее за N минут
    "speed_baseline_hours": 3,         # норма = средняя скорость за N часов
    "speed_min_baseline_mbps": 1.0,    # не следить за почти пустыми нодами
    "speed_confirm_minutes": 0,        # падение должно держаться N минут (0 — проверка сразу)
    "dns_refresh_minutes": 5,          # как часто сверять IP доменов с DNS (A-запись могли поменять вручную)
    "reserve_check_minutes": 120,      # как часто проверять резервные IP (их могли разбанить); 0 — не проверять
    "node_offline_alert_minutes": 10,  # «нода недоступна» — если не подключена дольше N минут
    "node_offline_repeat_minutes": 10,  # и дальше повторять каждые N минут, пока не вернётся (0 — один раз)
    # --- проверка IP после падения скорости ---
    "investigation_checks": 3,         # сколько раз проверять IP
    "investigation_interval_minutes": 30,
    "investigation_cooldown_minutes": 180,  # после завершения не начинать новую N минут
    "auto_switch_enabled": True,
    # --- периодическая проверка доменов/IP без привязанной ноды ---
    "unlinked_check_enabled": False,
    "unlinked_check_interval_minutes": 60,
    "tcp_check_port": 443,
    "atlas_fail_percent": 50,          # Red Atlas: бан, если из России не открывается столько % точек
    "atlas_max_wait_sec": 600,         # сколько ждать свободного места в лимите 6 проверок / 10 мин
    "latencylab_fail_percent": 50,     # запасной вариант, если wire не пришёл
    "bschek_units": [],                # единицы bschekbot: оператор|округ|БС; пусто — выберите в настройках
    "bschek_dpi": "off",               # off — только без Белого списка
    "bschek_fail_percent": 50,
    "enabled_checkers": None,          # None → default_enabled() из реестра
    "checker_delay_ms": 1000,
    # --- уведомления и прочее ---
    "daily_summary_enabled": True,
    "daily_summary_time": "07:00",
    "notify": {k: True for k in EVENT_TYPES},
    "events_retention_days": 90,
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
    # оставляем только существующие источники (старые могли быть удалены из кода)
    registered = set(all_checkers())
    enabled = [n for n in (result["enabled_checkers"] or []) if n in registered]
    result["enabled_checkers"] = enabled or default_enabled()
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

    # Раньше по умолчанию стоял скрытый выбор «*|цфо|off» (все операторы ЦФО без БС) —
    # убираем его, чтобы операторы выбирались только явно.
    if not await get_state(db, "migrated_bschek_units"):
        row = await db.get(Setting, "bschek_units")
        if row and json.loads(row.value) == ["*|цфо|off"]:
            row.value = json.dumps([])
        await set_state(db, "migrated_bschek_units", True)
        await db.commit()

    # Red Atlas — новый источник: включаем и ставим первым (остальные не трогаем).
    if not await get_state(db, "migrated_atlas"):
        row = await db.get(Setting, "enabled_checkers")
        if row:
            current = json.loads(row.value) or []
            if "atlas" not in current:
                row.value = json.dumps(["atlas", *current])
        await set_state(db, "migrated_atlas", True)
        await db.commit()

    # Ноды теперь идут в порядке Remnawave: прежний «свой» порядок сбрасываем один раз.
    if not await get_state(db, "migrated_remna_order"):
        await set_state(db, "node_order", [])
        await set_state(db, "migrated_remna_order", True)
        await db.commit()

    # Ежедневный отчёт теперь в 07:00 (было 10:00): меняем, только если стояло старое значение.
    if not await get_state(db, "migrated_summary_7"):
        row = await db.get(Setting, "daily_summary_time")
        if row and json.loads(row.value) == "10:00":
            row.value = json.dumps("07:00")
        await set_state(db, "migrated_summary_7", True)
        await db.commit()

    # Проверка при падении скорости запускается сразу (было: падение должно держаться 10 минут).
    if not await get_state(db, "migrated_speed_confirm_0"):
        row = await db.get(Setting, "speed_confirm_minutes")
        if row and json.loads(row.value) == 10:
            row.value = json.dumps(0)
        await set_state(db, "migrated_speed_confirm_0", True)
        await db.commit()

    # Порог падения скорости по умолчанию стал 99% (был 70%). Тем, у кого сохранено
    # старое значение по умолчанию, ставим новое один раз; своё значение не трогаем.
    if not await get_state(db, "migrated_speed_drop_99"):
        row = await db.get(Setting, "speed_drop_percent")
        if row and json.loads(row.value) == 70:
            row.value = json.dumps(99)
        await set_state(db, "migrated_speed_drop_99", True)
        await db.commit()
