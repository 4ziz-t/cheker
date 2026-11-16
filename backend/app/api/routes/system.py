from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import integrations
from app.core.config import get_settings
from app.core.database import get_db
from app.core.tasks import spawn
from app.core.timeutils import utcnow
from app.models import Domain, DomainIP, Event, Investigation, Node
from app.schemas import EventOut, InvestigationOut, normalize_ip
from app.services import settings_service
from app.services.domain_service import cycle_state, run_cycle
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


@router.get("/tools/check-ip")
async def tool_check_ip(
    ip: str = Query(...), port: int | None = Query(None, ge=1, le=65535), db: AsyncSession = Depends(get_db)
):
    try:
        ip = normalize_ip(ip)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    cfg = await settings_service.get_all(db)
    res = await check_ip(ip, cfg["enabled_checkers"], port or cfg["tcp_check_port"], cfg)
    return {"ip": ip, "blocked": res.blocked, "details": res.to_details(), "errors": res.errors}


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
