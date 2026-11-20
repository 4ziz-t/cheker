from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checkers import all_checkers
from app.core import integrations
from app.core.config import get_settings
from app.core.database import get_db
from app.core.tasks import spawn
from app.core.timeutils import utcnow
from app.models import Domain, DomainIP, Event, Investigation, Node
from app.schemas import DomainCreate, EventOut, InvestigationOut, normalize_ip
from app.services import settings_service
from app.services.domain_service import cycle_state, detect_current_ip, run_cycle
from app.services.events import errors
from app.services.ip_check import check_ip
from app.services.scheduler import scheduler

router = APIRouter(tags=["system"])


def _ts(t: float | None) -> str | None:
    if t is None:
        return None
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _status() -> dict:
    s = get_settings()
    return {
        "integrations": {
            "remnawave": integrations.remnawave_configured(),
            "cloudflare": integrations.cloudflare_configured(),
            "telegram": integrations.telegram_configured(),
        },
        "active_errors": [{"key": k, "message": v} for k, v in errors.active.items()],
        "check": {
            "running": cycle_state.running,
            "last_started_at": _ts(cycle_state.last_started_at),
            "last_finished_at": _ts(cycle_state.last_finished_at),
            "last_duration": cycle_state.last_duration,
        },
        "nodes_next_poll_at": _ts(scheduler.next_node_poll),
        "unlinked_next_check_at": _ts(scheduler.next_unlinked_check),
        "timezone": s.tz,
    }


@router.get("/system/status")
async def system_status():
    return _status()


@router.post("/system/check-now")
async def check_now():
    if cycle_state.running:
        raise HTTPException(status.HTTP_409_CONFLICT, "Проверка уже идёт")
    spawn(run_cycle())
    return {"ok": True}


class ToolCheckIn(BaseModel):
    target: str = Field(min_length=1, max_length=255)       # IPv4 или домен
    checker: str                                              # latencylab | bschek | …
    port: int | None = Field(None, ge=1, le=65535)
    units: list[str] | None = None                            # bschekbot: ключи единиц для этой проверки


async def _resolve_target(raw: str) -> tuple[str, str | None, str]:
    """IPv4 → как есть; домен → текущий IP (Cloudflare, затем DNS)."""
    try:
        return normalize_ip(raw), None, "ip"
    except ValueError:
        pass
    try:
        name = DomainCreate(name=raw).name
    except ValidationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Введите IPv4 или домен") from e
    found, source = await detect_current_ip(name)
    if not found:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Не удалось определить IP домена {name}: нет A-записи и не резолвится")
    return found, name, source


@router.post("/tools/check")
async def tool_check(data: ToolCheckIn, db: AsyncSession = Depends(get_db)):
    """Ручная проверка IP или домена ОДНИМ источником (кнопка на дашборде).

    Источник запускается, даже если он выключен в настройках, — пользователь нажал явно.
    """
    registry = all_checkers()
    if data.checker not in registry:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестный источник")
    ip, domain, source = await _resolve_target(data.target.strip())

    cfg = dict(await settings_service.get_all(db))
    port = data.port or cfg["tcp_check_port"]
    if data.units is not None:
        units = [u.strip() for u in data.units if u.strip()]
        if not units:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите хотя бы одного оператора")
        cfg["bschek_units"] = units

    res = await check_ip(ip, [data.checker], port, cfg)
    r = res.results[0] if res.results else None
    return {
        "input": data.target,
        "ip": ip,
        "domain": domain,
        "ip_source": source,
        "port": port,
        "checker": data.checker,
        "title": registry[data.checker].title,
        "blocked": r.blocked if r else None,
        "error": r.error if r else "Нет результата",
        "details": r.details if r else {},
    }


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db)):
    nodes = (await db.execute(select(Node))).scalars().all()
    active = [n for n in nodes if not n.is_disabled]
    domains = (await db.execute(select(Domain).order_by(Domain.name))).scalars().all()
    enabled = [d for d in domains if d.enabled]

    ip_rows = (await db.execute(select(DomainIP.ip, DomainIP.is_blocked))).all()
    unique: dict[str, bool | None] = {}
    for ip, blocked in ip_rows:
        prev = unique.get(ip)
        if blocked is True or prev is True:
            unique[ip] = True
        elif blocked is False or prev is False:
            unique[ip] = False
        else:
            unique[ip] = None

    since = utcnow() - timedelta(hours=24)
    day_counts = dict((await db.execute(
        select(Event.type, func.count()).where(Event.created_at >= since).group_by(Event.type)
    )).all())
    recent = (await db.execute(select(Event).order_by(Event.id.desc()).limit(12))).scalars().all()
    investigations = (await db.execute(
        select(Investigation).order_by(Investigation.id.desc()).limit(8)
    )).scalars().all()

    status_counts: dict[str, int] = {}
    for d in enabled:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1

    return {
        "nodes": {
            "total": len(active),
            "online": sum(1 for n in active if n.is_connected),
            "disabled": len(nodes) - len(active),
            "offline": [
                {"uuid": n.uuid, "name": n.name, "address": n.address,
                 "since": n.offline_since.isoformat(timespec="seconds") + "Z" if n.offline_since else None,
                 "message": n.last_status_message}
                for n in active if not n.is_connected
            ],
        },
        "domains": {
            "total": len(enabled),
            "disabled": len(domains) - len(enabled),
            "by_status": status_counts,
            "problems": [
                {"id": d.id, "name": d.name, "status": d.status, "message": d.status_message,
                 "current_ip": d.current_ip}
                for d in enabled if d.status != "ok"
            ],
        },
        "ips": {
            "total": len(unique),
            "blocked": sum(1 for v in unique.values() if v is True),
            "clean": sum(1 for v in unique.values() if v is False),
            "unknown": sum(1 for v in unique.values() if v is None),
        },
        "last_24h": {
            "blocked": day_counts.get("ip_blocked", 0),
            "switches_auto": day_counts.get("ip_switched_auto", 0),
            "switches_manual": day_counts.get("ip_switched_manual", 0),
            "node_offline": day_counts.get("node_offline", 0),
        },
        "recent_events": [EventOut.model_validate(e).model_dump(mode="json") for e in recent],
        "investigations": [InvestigationOut.model_validate(i).model_dump(mode="json") for i in investigations],
        "status": _status(),
    }
