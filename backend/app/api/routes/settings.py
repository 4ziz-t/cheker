import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.checkers import all_checkers
from app.core import integrations
from app.core.database import get_db
from app.core.http import get_http
from app.integrations import telegram
from app.integrations.cloudflare import CloudflareClient, CloudflareError
from app.integrations.remnawave import RemnawaveClient, RemnawaveError
from app.schemas import IntegrationsUpdate, SettingsUpdate
from app.services import settings_service
from app.services.events import errors
from app.services.scheduler import scheduler
from app.services.summary import build_summary

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_settings_(db: AsyncSession = Depends(get_db)):
    return {
        "values": await settings_service.get_all(db),
        "event_types": settings_service.EVENT_TYPES,
        "checkers": [
            {"name": c.name, "title": c.title, "description": c.description}
            for c in all_checkers().values()
        ],
    }


@router.put("")
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    patch = data.model_dump(exclude_none=True)
    if "enabled_checkers" in patch:
        unknown = set(patch["enabled_checkers"]) - set(all_checkers())
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестные источники: {', '.join(unknown)}")
        if not patch["enabled_checkers"]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужен хотя бы один источник проверки")
    if "notify" in patch:
        current = await settings_service.get(db, "notify")
        patch["notify"] = {**current, **{k: v for k, v in patch["notify"].items()
                                         if k in settings_service.EVENT_TYPES}}
    values = await settings_service.update(db, patch)
    scheduler.wake()
    return {"values": values}


@router.get("/checkers/status")
async def checkers_status():
    """Состояние источников (например, остаток лимита Latency Lab)."""
    result: dict[str, str | None] = {}
    for name, cls in all_checkers().items():
        try:
            result[name] = await asyncio.wait_for(cls(get_http()).status(), timeout=15)
        except Exception as e:  # noqa: BLE001
            result[name] = f"Ошибка: {e.__class__.__name__}"
    return result


@router.post("/test-telegram")
async def test_telegram():
    try:
        await telegram.send_message("✅ <b>Тестовое уведомление</b>\nCheker на связи.")
    except telegram.TelegramError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return {"ok": True}


@router.post("/test-summary")
async def test_summary(db: AsyncSession = Depends(get_db)):
    html_text, _ = await build_summary(db)
    try:
        await telegram.send_message(html_text)
    except telegram.TelegramError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return {"ok": True}


# ------------------------------------------------------------ интеграции

@router.get("/integrations")
async def get_integrations():
    return {"fields": integrations.public_view(), "groups": integrations.GROUPS}


@router.put("/integrations")
async def update_integrations(data: IntegrationsUpdate, db: AsyncSession = Depends(get_db)):
    unknown = set(data.values) - set(integrations.FIELD_MAP)
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Неизвестные поля: {', '.join(sorted(unknown))}")
    url = data.values.get("remnawave_url")
    if url and not url.strip().startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "URL панели должен начинаться с http:// или https://")
    await integrations.update(db, data.values)
    errors.active.clear()  # после смены токенов ошибки перепроверятся заново
    scheduler.wake()
    return {"fields": integrations.public_view(), "groups": integrations.GROUPS}


@router.post("/integrations/test/{group}")
async def test_integration(group: str):
    try:
        if group == "remnawave":
            nodes = await RemnawaveClient().get_nodes()
            return {"ok": True, "message": f"Подключено, нод в панели: {len(nodes)}"}
        if group == "cloudflare":
            message = await CloudflareClient().verify_token()
            return {"ok": "не видит ни одной зоны" not in message, "message": message}
        if group == "telegram":
            await telegram.send_message("✅ <b>Тестовое уведомление</b>\nCheker на связи.")
            return {"ok": True, "message": "Сообщение отправлено"}
        if group in ("latencylab", "bschek"):
            msg = await all_checkers()[group](get_http()).status()
            ok = bool(msg) and not msg.startswith(("Ошибка", "Ключ не задан", "Токен не задан", "Не удалось"))
            return {"ok": ok, "message": msg or "—"}
    except (RemnawaveError, CloudflareError, telegram.TelegramError) as e:
        return {"ok": False, "message": str(e)}
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестная интеграция")


@router.get("/bschek/units")
async def bschek_units():
    """Единицы bschekbot (оператор × округ × Белый список) — для выбора в настройках."""
    from app.checkers.bschek import BschekChecker, BschekError

    try:
        units = await BschekChecker(get_http()).units()
    except BschekError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return [
        {k: u.get(k) for k in ("op_key", "operator", "name", "region", "region_code", "dpi", "channel_state", "probeable")}
        for u in units
    ]
