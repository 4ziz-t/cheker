"""Ежедневная проверка всех IP через Red Atlas и отчёт одним сообщением (по умолчанию в 07:00).

У Red Atlas лимит — 6 живых проверок за 10 минут, поэтому IP встают в очередь и проверяются
по одному; срочные проверки (падение скорости, кнопки) при этом идут вперёд очереди.
После проверки — один отчёт в Telegram, затем для доменов, у которых текущий IP оказался
в бане, запускается обычная проверка с заменой IP.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from app.checkers import atlas
from app.core.database import SessionLocal
from app.core.timeutils import utcnow
from app.models import Domain
from app.models.domain import DomainKind
from app.services import settings_service
from app.services.ip_check import aggregate_stored, check_ip

log = logging.getLogger(__name__)


@dataclass
class SweepState:
    running: bool = False
    total: int = 0
    done: int = 0
    started_at: float | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


sweep_state = SweepState()


@dataclass
class DomainStat:
    name: str
    ok: int = 0
    banned: int = 0
    unknown: int = 0
    current_banned: bool = False


async def atlas_sweep() -> tuple[dict[int, DomainStat], float]:
    """Проверить все IP видимых доменов через Red Atlas. Возвращает статистику и длительность (с)."""
    from app.services.domain_service import domain_lock, hidden_domain_names

    started = time.monotonic()
    stats: dict[int, DomainStat] = {}
    async with SessionLocal() as db:
        cfg = await settings_service.get_all(db)
        options = {**cfg, "atlas_max_wait_sec": 3600}  # фоновая проверка может ждать очереди долго
        hidden = await hidden_domain_names(db)
        domains = [
            d for d in (await db.execute(select(Domain).where(Domain.enabled.is_(True)))).scalars().all()
            if d.name not in hidden
        ]
        sweep_state.total = sum(len(d.ips) or (1 if d.kind == DomainKind.IP else 0) for d in domains)
        sweep_state.done = 0
        for d in domains:
            st = stats.setdefault(d.id, DomainStat(d.name))
            for entry in list(d.ips):
                with atlas.background():
                    res = await check_ip(entry.ip, ["atlas"], d.check_port, options)
                sweep_state.done += 1
                async with domain_lock(d.id):
                    await db.refresh(entry)
                    try:
                        details = json.loads(entry.details) if entry.details else {}
                    except ValueError:
                        details = {}
                    if not isinstance(details, dict):
                        details = {}
                    fresh = res.to_details().get("atlas")
                    if fresh is not None:
                        details["atlas"] = fresh
                    # итог — по всем выбранным для IP источникам (свежий Red Atlas + прошлые ответы остальных)
                    agg = aggregate_stored(entry.ip, details, entry.checker_list or list(cfg["enabled_checkers"]))
                    entry.details = json.dumps(details, ensure_ascii=False)
                    entry.last_checked_at = utcnow()
                    if agg is not None and agg.blocked is not None:
                        if agg.blocked != entry.is_blocked:
                            entry.blocked_since = utcnow() if agg.blocked else None
                        entry.is_blocked = agg.blocked
                    await db.commit()
                if entry.is_blocked is True:
                    st.banned += 1
                    if entry.ip == d.current_ip:
                        st.current_banned = True
                elif entry.is_blocked is False:
                    st.ok += 1
                else:
                    st.unknown += 1
    return stats, time.monotonic() - started


async def _run() -> None:
    from app.services.domain_service import check_now
    from app.services.summary import send_summary

    sweep_state.running = True
    sweep_state.started_at = time.time()
    stats: dict[int, DomainStat] | None = None
    duration = 0.0
    try:
        try:
            stats, duration = await atlas_sweep()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — отчёт всё равно отправим, без раздела проверки
            log.exception("Ошибка ежедневной проверки IP")
        async with SessionLocal() as db:
            await send_summary(db, sweep=stats, sweep_seconds=duration)
        # текущий IP в бане — обычная проверка домена: смена IP и уведомление
        for domain_id, st in (stats or {}).items():
            if st.current_banned:
                await check_now(domain_id)
    finally:
        sweep_state.running = False


def start_daily() -> bool:
    """Запустить проверку всех IP и отчёт в фоне. False — уже идёт."""
    if sweep_state.running:
        return False
    sweep_state.task = asyncio.create_task(_run(), name="daily-sweep")
    return True


def cancel_daily() -> bool:
    if sweep_state.task and not sweep_state.task.done():
        sweep_state.task.cancel()
        return True
    return False
