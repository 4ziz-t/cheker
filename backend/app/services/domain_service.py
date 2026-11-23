"""Логика доменов: синхронизация A-записи, проверка пула IP, автосмена."""
import asyncio
import json
import logging
import socket
import time
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.checkers import all_checkers
from app.core import integrations
from app.core.database import SessionLocal
from app.core.timeutils import utcnow
from app.integrations.cloudflare import CloudflareClient, CloudflareError
from app.models import Domain, DomainIP
from app.models.domain import DomainKind, DomainSource, DomainStatus
from app.schemas import is_ipv4
from app.services import settings_service
from app.services.events import errors, record
from app.services.ip_check import AggregatedResult, IPCheckCache

log = logging.getLogger(__name__)

_domain_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_cycle_lock = asyncio.Lock()


class DnsConflictError(Exception):
    pass


@dataclass
class CycleState:
    running: bool = False
    last_started_at: float | None = None
    last_finished_at: float | None = None
    last_duration: float | None = None
    checked_domains: int = 0


cycle_state = CycleState()


def domain_lock(domain_id: int) -> asyncio.Lock:
    return _domain_locks[domain_id]


# ---------------------------------------------------------------- DNS

async def sync_dns(db: AsyncSession, domain: Domain) -> None:
    """Читает A-запись из Cloudflare и обновляет current_ip."""
    cf = CloudflareClient()
    if not domain.cf_zone_id:
        domain.cf_zone_id = await cf.find_zone_id(domain.name)
    records = await cf.get_a_records(domain.cf_zone_id, domain.name)
    if len(records) > 1:
        ips = ", ".join(r.content for r in records)
        raise DnsConflictError(f"У домена {len(records)} A-записи ({ips}), должна быть одна")

    new_ip = records[0].content if records else None
    domain.cf_record_id = records[0].id if records else None
    old_ip = domain.current_ip
    domain.current_ip = new_ip
    if old_ip and new_ip != old_ip:
        await record(
            db, "dns_changed", "A-запись изменена вне панели",
            f"{domain.name}: {old_ip} → {new_ip or 'запись удалена'}",
            level="warning", domain=domain.name, ip=new_ip, emoji="✏️",
        )


async def switch_ip(db: AsyncSession, domain: Domain, new_ip: str, *, manual: bool, reason: str = "") -> None:
    """Меняет A-запись в Cloudflare. Бросает CloudflareError при ошибке."""
    cf = CloudflareClient()
    if not domain.cf_zone_id:
        domain.cf_zone_id = await cf.find_zone_id(domain.name)

    if domain.cf_record_id:
        try:
            await cf.update_a_record(domain.cf_zone_id, domain.cf_record_id, new_ip)
        except CloudflareError:
            domain.cf_record_id = None  # запись могли удалить — попробуем найти заново

    if not domain.cf_record_id:
        records = await cf.get_a_records(domain.cf_zone_id, domain.name)
        if len(records) > 1:
            raise DnsConflictError(f"У домена {len(records)} A-записи, должна быть одна")
        if records:
            rec = await cf.update_a_record(domain.cf_zone_id, records[0].id, new_ip)
        else:
            rec = await cf.create_a_record(domain.cf_zone_id, domain.name, new_ip)
        domain.cf_record_id = rec.id

    old_ip = domain.current_ip
    domain.current_ip = new_ip
    domain.last_switch_at = utcnow()

    entry = next((e for e in domain.ips if e.ip == new_ip), None)
    if entry is None or entry.is_blocked is None:
        domain.status, domain.status_message = DomainStatus.UNKNOWN, "IP ещё не проверен"
    elif entry.is_blocked:
        domain.status, domain.status_message = DomainStatus.BLOCKED, "Назначен IP, который числится в бане"
    else:
        domain.status, domain.status_message = DomainStatus.OK, ""
        domain.no_ips_alerted = False
    await db.commit()

    kind = "ip_switched_manual" if manual else "ip_switched_auto"
    title = "Ручная смена IP" if manual else "IP заменён автоматически"
    msg = f"{domain.name}: {old_ip or '—'} → {new_ip}"
    if reason:
        msg += f"\nПричина: {reason}"
    await record(db, kind, title, msg, level="success" if not manual else "info",
                 domain=domain.name, ip=new_ip, emoji="🔁")


async def _find_candidate(
    db: AsyncSession, domain: Domain, current_ip: str | None, cache: IPCheckCache
) -> str | None:
    """Следующий доступный IP по порядку после текущего (по кругу).

    Каждый кандидат проверяется прямо сейчас (результат кэшируется на цикл),
    поэтому запросы тратятся только тогда, когда действительно нужно переключаться.
    """
    ips = sorted(domain.ips, key=lambda e: e.position)
    if not ips:
        return None
    idx = next((i for i, e in enumerate(ips) if e.ip == current_ip), -1)
    n = len(ips)
    for step in range(1, n + 1):
        entry = ips[(idx + step) % n]
        if entry.ip == current_ip:
            continue
        res = await cache.get(entry.ip, domain.check_port)
        await _report_checker_errors(db, res)
        await _apply_result(db, domain, entry, res)
        await db.commit()
        if res.blocked is False:
            return entry.ip
    return None


async def detect_current_ip(name: str) -> tuple[str | None, str]:
    """Определяет текущий IP домена: сначала A-запись в Cloudflare, затем обычный DNS.

    Возвращает (ip, источник). Источник: cloudflare | dns | none.
    """
    if integrations.cloudflare_configured():
        try:
            cf = CloudflareClient()
            zone = await cf.find_zone_id(name)
            records = await cf.get_a_records(zone, name)
            if records:
                return records[0].content, "cloudflare"
        except CloudflareError as e:
            log.info("Cloudflare не дал IP для %s: %s", name, e)
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM), timeout=10
        )
        if infos:
            return infos[0][4][0], "dns"
    except (OSError, asyncio.TimeoutError):
        pass
    return None, "none"


IGNORED_KEY = "ignored_node_addresses"


async def get_ignored(db: AsyncSession) -> list[str]:
    return list(await settings_service.get_state(db, IGNORED_KEY, []))


async def set_ignored(db: AsyncSession, name: str, ignored: bool) -> None:
    items = set(await get_ignored(db))
    (items.add if ignored else items.discard)(name)
    await settings_service.set_state(db, IGNORED_KEY, sorted(items))
    await db.commit()


async def create_entry(
    db: AsyncSession,
    name: str,
    *,
    ips: list[str] | None = None,
    auto_switch: bool = False,
    enabled: bool = True,
    notes: str = "",
    source: str = DomainSource.MANUAL,
    check_port: int | None = None,
) -> tuple[Domain, str | None, str]:
    """Создаёт домен (или запись-IP). Текущий IP домена определяется автоматически
    и добавляется в список для проверки. Возвращает (домен, найденный IP, источник)."""
    ips = list(ips or [])
    if is_ipv4(name):
        kind, detected, src = DomainKind.IP, name, "ip"
        ips, auto_switch = [name], False
    else:
        kind = DomainKind.DOMAIN
        detected, src = await detect_current_ip(name)
        if detected and detected not in ips:
            ips.insert(0, detected)

    d = Domain(
        name=name, kind=kind, source=source, auto_switch=auto_switch, enabled=enabled,
        notes=notes, check_port=check_port, current_ip=detected,
    )
    d.ips = [DomainIP(ip=ip, position=i) for i, ip in enumerate(ips)]
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d, detected, src


# ---------------------------------------------------------------- проверка

async def _report_checker_errors(db: AsyncSession, res: AggregatedResult) -> None:
    registry = all_checkers()
    for r in res.results:
        cls = registry.get(r.checker)
        title = f"источник {cls.title if cls else r.checker}"
        if r.error:
            await errors.report(db, f"checker:{r.checker}", title, r.error)
        else:
            await errors.resolve(db, f"checker:{r.checker}", title)


async def _apply_result(db: AsyncSession, domain: Domain, entry: DomainIP, res: AggregatedResult) -> None:
    now = utcnow()
    entry.last_checked_at = now
    entry.details = json.dumps(res.to_details(), ensure_ascii=False)
    entry.last_error = "; ".join(res.errors) or None
    if res.blocked is None:
        return

    prev = entry.is_blocked
    entry.is_blocked = res.blocked
    is_current = entry.ip == domain.current_ip
    role = "текущий IP домена" if is_current else "резервный IP"

    if res.blocked and prev is not True:
        entry.blocked_since = now
        await record(
            db, "ip_blocked", "IP в бане",
            f"{entry.ip} — {domain.name} ({role})",
            level="error" if is_current else "warning", domain=domain.name, ip=entry.ip, emoji="⛔",
        )
    elif not res.blocked and prev is True:
        entry.blocked_since = None
        await record(
            db, "ip_unblocked", "IP разбанен",
            f"{entry.ip} — {domain.name} ({role})",
            level="success", domain=domain.name, ip=entry.ip, emoji="🟢",
        )


async def _set_status(db: AsyncSession, domain: Domain, status: str, message: str = "") -> None:
    domain.status, domain.status_message = status, message
    await db.commit()


async def process_domain(db: AsyncSession, domain: Domain, cache: IPCheckCache, global_auto: bool) -> None:
    async with domain_lock(domain.id):
        # список IP могли изменить из панели, пока шёл цикл
        await db.refresh(domain)
        domain.last_checked_at = utcnow()

        if domain.kind == DomainKind.IP:
            await _process_ip_entry(db, domain, cache)
            return

        # 1. Текущий IP берём без Cloudflare: сохранённый, а если его нет — из обычного DNS.
        #    В Cloudflare идём только если IP в бане и его нужно менять.
        dns_ip = await resolve_dns(domain.name)
        if dns_ip:
            domain.current_ip = dns_ip
        if not domain.current_ip:
            await _set_status(db, domain, DomainStatus.NO_RECORD, "Домен не резолвится — нет текущего IP")
            return

        # пустой список — добавляем текущий IP домена, чтобы было что проверять
        if not domain.ips:
            domain.ips = [DomainIP(ip=domain.current_ip, position=0)]
            await db.commit()
            await db.refresh(domain)

        # 2. Проверяем только текущий IP — экономим запросы к источникам.
        #    Резервные IP проверяются, только когда нужно на что-то переключиться.
        current_entry = next((e for e in domain.ips if e.ip == domain.current_ip), None)
        res = await cache.get(domain.current_ip, domain.check_port)
        await _report_checker_errors(db, res)
        if current_entry is not None:
            await _apply_result(db, domain, current_entry, res)
        await db.commit()

        # 3. решение
        if res.blocked is True:
            auto = domain.auto_switch and global_auto
            await handle_current_banned(db, domain, cache, auto)
        elif res.blocked is False:
            domain.no_ips_alerted = False
            msg = "" if current_entry else "Текущий IP не из списка домена"
            await _set_status(db, domain, DomainStatus.OK, msg)
        else:
            await _set_status(db, domain, DomainStatus.ERROR,
                              f"Не удалось проверить IP: {'; '.join(res.errors) or '—'}")


async def resolve_dns(name: str) -> str | None:
    """IPv4 домена через обычный DNS (без Cloudflare API)."""
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM), timeout=10
        )
        return infos[0][4][0] if infos else None
    except (OSError, asyncio.TimeoutError):
        return None


async def handle_current_banned(db: AsyncSession, domain: Domain, cache: IPCheckCache, auto: bool) -> str | None:
    """Текущий IP в бане: ищем следующий доступный и переключаем A-запись.

    Возвращает новый IP или None.
    """
    if domain.kind == DomainKind.IP:
        await _set_status(db, domain, DomainStatus.BLOCKED, "IP в бане. Это IP-адрес, сменить его автоматически нельзя")
        return None
    if not auto:
        await _set_status(db, domain, DomainStatus.BLOCKED, "Текущий IP в бане, автосмена выключена")
        return None
    # нет резервных IP — менять не на что, в Cloudflare не идём
    if not any(e.ip != domain.current_ip for e in domain.ips):
        if not domain.no_ips_alerted:
            domain.no_ips_alerted = True
            await record(
                db, "no_available_ips", "Нет резервных IP",
                f"{domain.name}: текущий {domain.current_ip} в бане, а других IP в списке домена нет. "
                f"Добавьте резервные IP — тогда Cheker сменит A-запись сам.",
                level="error", domain=domain.name, emoji="🆘",
            )
        await _set_status(db, domain, DomainStatus.NO_IPS, "IP в бане, резервных IP в списке нет")
        return None
    if not integrations.cloudflare_configured():
        await _set_status(db, domain, DomainStatus.BLOCKED, "IP в бане, но Cloudflare не настроен — сменить нечем")
        return None

    # только теперь идём в Cloudflare: сверяем A-запись перед сменой
    banned_ip = domain.current_ip
    try:
        await sync_dns(db, domain)
        await errors.resolve(db, "cloudflare", "Cloudflare")
    except (CloudflareError, DnsConflictError) as e:
        domain.cf_zone_id = None
        await errors.report(db, "cloudflare", "Cloudflare", f"{domain.name}: {e}")
        await _set_status(db, domain, DomainStatus.BLOCKED, f"IP {banned_ip} в бане, но сменить не удалось: {e}")
        return None
    if domain.current_ip != banned_ip:
        # A-запись уже указывает на другой IP (сменили вручную) — проверим её в следующий раз
        await _set_status(db, domain, DomainStatus.UNKNOWN,
                          f"A-запись уже не {banned_ip}, а {domain.current_ip or 'пусто'} — проверьте снова")
        return None

    candidate = await _find_candidate(db, domain, domain.current_ip, cache)
    if candidate:
        await _safe_switch(db, domain, candidate, f"{domain.current_ip} в бане")
        return candidate if domain.current_ip == candidate else None
    if not domain.no_ips_alerted:
        domain.no_ips_alerted = True
        await record(
            db, "no_available_ips", "Нет доступных IP",
            f"{domain.name}: текущий {domain.current_ip} в бане, резервные IP тоже в бане "
            f"или их не удалось проверить. Добавьте новые IP.",
            level="error", domain=domain.name, emoji="🆘",
        )
    await _set_status(db, domain, DomainStatus.NO_IPS, "Все IP из списка в бане")
    return None


async def check_single_ip(db: AsyncSession, domain: Domain, ip: str) -> None:
    """Ручная проверка одного IP из списка домена (кнопка во фронте)."""
    entry = next((e for e in domain.ips if e.ip == ip), None)
    if entry is None:
        raise ValueError("IP нет в списке домена")
    cfg = await settings_service.get_all(db)
    cache = IPCheckCache(cfg)
    async with domain_lock(domain.id):
        res = await cache.get(ip, domain.check_port)
        await _report_checker_errors(db, res)
        await _apply_result(db, domain, entry, res)
        if ip == domain.current_ip and res.blocked is not None:
            domain.last_checked_at = utcnow()
        await db.commit()


async def _process_ip_entry(db: AsyncSession, domain: Domain, cache: IPCheckCache) -> None:
    """Запись-IP (например, нода, у которой адрес — голый IP): только мониторинг, без смены."""
    domain.current_ip = domain.name
    if not domain.ips:
        domain.ips = [DomainIP(ip=domain.name, position=0)]
        await db.commit()
        await db.refresh(domain)
    entry = domain.ips[0]
    res = await cache.get(entry.ip, domain.check_port)
    await _report_checker_errors(db, res)
    await _apply_result(db, domain, entry, res)
    if res.blocked is True:
        await _set_status(db, domain, DomainStatus.BLOCKED, "IP в бане. Это IP-адрес, сменить его автоматически нельзя")
    elif res.blocked is False:
        await _set_status(db, domain, DomainStatus.OK, "")
    else:
        await _set_status(db, domain, DomainStatus.ERROR, f"Не удалось проверить IP: {'; '.join(res.errors) or '—'}")


async def _safe_switch(db: AsyncSession, domain: Domain, ip: str, reason: str) -> None:
    try:
        await switch_ip(db, domain, ip, manual=False, reason=reason)
        await errors.resolve(db, "cloudflare", "Cloudflare")
    except (CloudflareError, DnsConflictError) as e:
        await errors.report(db, "cloudflare", "Cloudflare", f"Не удалось сменить IP {domain.name}: {e}")
        await _set_status(db, domain, DomainStatus.ERROR, f"Не удалось сменить IP: {e}")


# ---------------------------------------------------------------- цикл

async def unlinked_domain_ids(db: AsyncSession) -> list[int]:
    """Включённые домены/IP, адрес которых не совпадает ни с одной нодой Remnawave."""
    from app.models import Node  # локальный импорт, чтобы не было цикла моделей

    addresses = {
        (a or "").strip().lower().rstrip(".")
        for a in (await db.execute(select(Node.address))).scalars().all()
    }
    rows = (await db.execute(select(Domain.id, Domain.name).where(Domain.enabled.is_(True)))).all()
    return [i for i, name in rows if name not in addresses]

async def run_cycle(domain_ids: list[int] | None = None) -> bool:
    """Полная проверка доменов. Возвращает False, если цикл уже идёт."""
    if domain_ids is None and _cycle_lock.locked():
        return False
    async with _cycle_lock:
        cycle_state.running = True
        cycle_state.last_started_at = time.time()
        count = 0
        try:
            async with SessionLocal() as db:
                cfg = await settings_service.get_all(db)
                cache = IPCheckCache(cfg)
                q = select(Domain).where(Domain.enabled.is_(True)).order_by(Domain.name)
                if domain_ids is not None:
                    q = select(Domain).where(Domain.id.in_(domain_ids))
                domains = (await db.execute(q)).scalars().all()
                for d in domains:
                    try:
                        await process_domain(db, d, cache, cfg["auto_switch_enabled"])
                        count += 1
                    except Exception as e:  # noqa: BLE001
                        log.exception("Ошибка проверки домена %s", d.name)
                        await db.rollback()
                        await record(db, "integration_error", "Ошибка проверки домена",
                                     f"{d.name}: {e}", level="error", domain=d.name)
                if domain_ids is None:
                    await settings_service.set_state(db, "last_check_at", utcnow().isoformat())
                    await db.commit()
        finally:
            cycle_state.running = False
            cycle_state.last_finished_at = time.time()
            cycle_state.last_duration = cycle_state.last_finished_at - (cycle_state.last_started_at or 0)
            cycle_state.checked_domains = count
    return True
