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
from app.services import domain_service, node_service, settings_service
from app.services.daily import cancel_daily, sweep_state
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
            "running": cycle_state.running or sweep_state.running,
            "kind": "daily" if sweep_state.running else ("all" if cycle_state.running else None),
            "done": sweep_state.done if sweep_state.running else cycle_state.checked_domains,
            "total": sweep_state.total if sweep_state.running else cycle_state.total,
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
    cycle_state.task = spawn(run_cycle())
    return {"ok": True}


@router.post("/system/check-cancel")
async def check_cancel():
    """Отменить проверку всех доменов (кнопка) или ежедневную проверку всех IP."""
    cancelled = False
    if cycle_state.task and not cycle_state.task.done():
        cycle_state.task.cancel()
        cancelled = True
    if cancel_daily():
        cancelled = True
    if not cancelled:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сейчас ничего не проверяется")
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

    # ручная проверка не должна висеть долго в очереди лимита Red Atlas
    cfg["atlas_max_wait_sec"] = min(int(cfg.get("atlas_max_wait_sec") or 0), 45)
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
    hidden = await domain_service.hidden_domain_names(db)  # домены отключённых нод
    domains = [d for d in (await db.execute(select(Domain).order_by(Domain.name))).scalars().all()
               if d.name not in hidden]
    enabled = [d for d in domains if d.enabled]
    visible_ids = {d.id for d in domains}

    raw_ips = [row for row in (await db.execute(
        select(DomainIP.ip, DomainIP.is_blocked, DomainIP.domain_id))).all() if row[2] in visible_ids]
    ip_rows = [(ip, b) for ip, b, _ in raw_ips]
    banned_domains = sorted({did for _, b, did in raw_ips if b is True})  # домены, где есть IP в бане
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

    # скорость нод — в том же порядке, что и на вкладке «Ноды» (как в Remnawave)
    order = {n.uuid: i for i, n in enumerate(await node_service.ordered_nodes(db))}
    by_name = {d.name: d.id for d in domains}
    speeds = [
        {
            "uuid": n.uuid, "name": n.name, "country_code": n.country_code,
            "online": bool(n.is_connected),
            "now_bps": n.speed_now_bps, "avg_bps": n.speed_bps, "norm_bps": n.baseline_bps,
            "drop_since": n.speed_drop_since.isoformat(timespec="seconds") + "Z" if n.speed_drop_since else None,
            "users_online": n.users_online,
            "domain_id": by_name.get((n.address or "").strip().lower().rstrip(".")),
        }
        for n in sorted(active, key=lambda n: order.get(n.uuid, len(order)))
    ]
    last_poll = max((n.updated_at for n in nodes if n.updated_at), default=None)

    return {
        "nodes": {
            "total": len(active),
            "online": sum(1 for n in active if n.is_connected),
            "disabled": 0,  # отключённые в панели ноды в Cheker не показываются
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
            "banned_domains": banned_domains,
        },
        "last_24h": {
            "blocked": day_counts.get("ip_blocked", 0),
            "switches_auto": day_counts.get("ip_switched_auto", 0),
            "switches_manual": day_counts.get("ip_switched_manual", 0),
            "node_offline": day_counts.get("node_offline", 0),
            "speed_drops": day_counts.get("speed_drop", 0),
        },
        "speeds": speeds,
        "nodes_updated_at": last_poll.isoformat(timespec="seconds") + "Z" if last_poll else None,
        "recent_events": [EventOut.model_validate(e).model_dump(mode="json") for e in recent],
        "investigations": [InvestigationOut.model_validate(i).model_dump(mode="json") for i in investigations],
        "status": _status(),
    }
