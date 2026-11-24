"""Проверка IP после падения скорости ноды.

Когда у ноды упала скорость, для привязанного к ней домена (адрес ноды = домен/IP)
запускается «расследование»: текущий IP проверяется включёнными источниками (основной — Red Atlas) N раз (по умолчанию 3)
с интервалом (по умолчанию 30 минут).

  • все N проверок показали бан → IP в бане: смена A-записи + уведомление;
  • хоть одна проверка показала, что IP доступен → проверка останавливается (экономим запросы):
      – скорость к этому времени вернулась к норме → «скорость восстановилась», без тревоги;
      – скорость всё ещё ниже нормы → «IP не в бане, но скорость ноды низкая»;
  • перед каждой проверкой смотрим на ноду: ушла в offline → проверка отменяется
    (придёт отдельное уведомление «нода offline»); скорость восстановилась → проверка не нужна;
  • запуск вручную (кнопка «Запустить») — просто проверка IP: о «проблемах с нодой» не сообщает;
  • ошибки проверки не засчитываются; после 2×N попыток — «проверить не удалось».
"""
import json
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.timeutils import utcnow
from app.models import Domain, Investigation, Node
from app.models.domain import DomainKind, DomainStatus
from app.models.investigation import InvestigationStatus as S
from app.services import domain_service, settings_service
from app.services.events import errors, record
from app.services.ip_check import IPCheckCache
from app.services.speed import mbps

log = logging.getLogger(__name__)


async def active_for_domain(db: AsyncSession, domain_id: int) -> Investigation | None:
    q = select(Investigation).where(Investigation.domain_id == domain_id, Investigation.status == S.ACTIVE)
    return (await db.execute(q)).scalars().first()


async def _in_cooldown(db: AsyncSession, domain_id: int, minutes: int) -> bool:
    if minutes <= 0:
        return False
    since = utcnow() - timedelta(minutes=minutes)
    q = select(Investigation.id).where(
        Investigation.domain_id == domain_id,
        Investigation.status != S.ACTIVE,
        Investigation.status != S.CANCELLED,
        Investigation.finished_at >= since,
    )
    return (await db.execute(q)).first() is not None


async def start(
    db: AsyncSession, domain: Domain, *, reason: str, node: Node | None = None, force: bool = False,
    trigger: str = "speed",
) -> Investigation | None:
    """Запустить проверку домена. force — без учёта паузы после прошлой проверки."""
    if await active_for_domain(db, domain.id):
        return None
    cfg = await settings_service.get_all(db)
    if not force and await _in_cooldown(db, domain.id, int(cfg["investigation_cooldown_minutes"])):
        return None
    inv = Investigation(
        domain_id=domain.id,
        domain_name=domain.name,
        node_uuid=node.uuid if node else None,
        node_name=node.name if node else "",
        ip=domain.current_ip or (domain.name if domain.kind == DomainKind.IP else None),
        reason=reason,
        trigger=trigger,
        checks_total=int(cfg["investigation_checks"]),
        next_check_at=utcnow(),
    )
    db.add(inv)
    await db.commit()
    return inv


async def on_speed_drop(db: AsyncSession, node: Node, current: float, baseline: float) -> None:
    """Вызывается из опроса нод, когда падение скорости подтвердилось."""
    drop = round((1 - current / baseline) * 100) if baseline else 0
    reason = f"скорость упала на {drop}%: {mbps(current)} при норме {mbps(baseline)}"
    address = (node.address or "").strip().lower().rstrip(".")
    domains = (await db.execute(
        select(Domain).where(Domain.name == address, Domain.enabled.is_(True))
    )).scalars().all()

    started = []
    for d in domains:
        if await start(db, d, reason=reason, node=node):
            started.append(d.name)

    cfg = await settings_service.get_all(db)
    if started:
        await record(
            db, "speed_drop", "Упала скорость ноды",
            f"{node.name} ({node.address}): {reason}.\n"
            f"Проверяю IP домена {', '.join(started)}: {cfg['investigation_checks']} раза "
            f"каждые {cfg['investigation_interval_minutes']} мин.",
            level="warning", node=node.name, domain=started[0], emoji="📉",
        )
    elif not domains:
        await record(
            db, "speed_drop", "Упала скорость ноды",
            f"{node.name} ({node.address}): {reason}.\nДомен ноды не добавлен во вкладку «Домены» — проверять нечего.",
            level="warning", node=node.name, emoji="📉",
        )


def _results(inv: Investigation) -> list[dict]:
    try:
        return json.loads(inv.results or "[]")
    except ValueError:
        return []


async def _finish(db: AsyncSession, inv: Investigation, status: str, summary: str) -> None:
    inv.status = status
    inv.summary = summary
    inv.finished_at = utcnow()
    inv.next_check_at = None
    await db.commit()


def _speed_state(node: Node | None, cfg: dict) -> str:
    """dropped — скорость всё ещё ниже нормы; recovered — вернулась; unknown — данных нет."""
    if node is None or node.speed_bps is None or not node.baseline_bps:
        return "unknown"
    share = float(cfg["speed_drop_percent"]) / 100
    min_base = float(cfg["speed_min_baseline_mbps"]) * 1_000_000 / 8
    if node.baseline_bps < min_base:
        return "unknown"
    return "dropped" if node.speed_bps <= node.baseline_bps * (1 - share) else "recovered"


def _speed_text(node: Node) -> str:
    drop = round((1 - node.speed_bps / node.baseline_bps) * 100) if node.baseline_bps else 0
    tail = f", ниже нормы на {drop}%" if drop > 0 else ""
    return f"сейчас {mbps(node.speed_bps)} при норме {mbps(node.baseline_bps)}{tail}"


async def _recovered(db: AsyncSession, inv: Investigation, node: Node, ip: str | None, checked: bool) -> None:
    label = inv.node_name or inv.domain_name
    if checked:
        text = f"{label}: скорость восстановилась ({_speed_text(node)}), IP {ip} не в бане. Всё в порядке."
    else:
        text = f"{label}: скорость восстановилась ({_speed_text(node)}) — проверка IP не понадобилась."
    await _finish(db, inv, S.RECOVERED, text)
    await record(db, "speed_drop", "Скорость ноды восстановилась", text,
                 level="success", node=inv.node_name or None, domain=inv.domain_name, emoji="📈")


async def _step(db: AsyncSession, inv: Investigation) -> None:
    domain = await db.get(Domain, inv.domain_id)
    if domain is None or not domain.enabled:
        await _finish(db, inv, S.CANCELLED, "Домен удалён или выключен")
        return

    cfg = await settings_service.get_all(db)
    by_speed = inv.trigger != "manual"
    node = await db.get(Node, inv.node_uuid) if inv.node_uuid else None

    if by_speed:
        if node is None:
            await _finish(db, inv, S.CANCELLED, "Нода удалена из списка — проверка остановлена")
            return
        if not node.is_connected or node.is_disabled:
            await _finish(db, inv, S.CANCELLED,
                          "Нода offline — проверка IP остановлена (о самой ноде придёт отдельное уведомление)")
            return
        if _speed_state(node, cfg) == "recovered":
            await _recovered(db, inv, node, inv.ip, checked=False)
            return
    interval = int(cfg["investigation_interval_minutes"])
    cache = IPCheckCache(cfg)

    async with domain_service.domain_lock(domain.id):
        await db.refresh(domain)
        # текущий IP — из обычного DNS (Cloudflare нужен только для смены IP при бане)
        if domain.kind == DomainKind.DOMAIN:
            dns_ip = await domain_service.resolve_dns(domain.name)
            if dns_ip:
                domain.current_ip = dns_ip
        ip = domain.name if domain.kind == DomainKind.IP else domain.current_ip
        if not ip:
            await _finish(db, inv, S.FAILED, "У домена нет текущего IP")
            return
        inv.ip = ip

        res = await cache.get(ip, domain.check_port)
        await domain_service._report_checker_errors(db, res)  # noqa: SLF001
        entry = next((e for e in domain.ips if e.ip == ip), None)

        results = _results(inv)
        results.append({"at": utcnow().isoformat(timespec="seconds") + "Z", "ip": ip,
                        "blocked": res.blocked, "error": "; ".join(res.errors) or None})
        inv.results = json.dumps(results, ensure_ascii=False)
        inv.attempts += 1
        domain.last_checked_at = utcnow()

        # ошибка проверки — не засчитываем
        if res.blocked is None:
            if inv.attempts >= inv.checks_total * 2:
                await _finish(db, inv, S.FAILED, f"Не удалось проверить IP: {'; '.join(res.errors)}")
                await record(db, "integration_error", "Проверка IP не удалась",
                             f"{domain.name} ({ip}): {'; '.join(res.errors)}", level="error", domain=domain.name)
            else:
                inv.next_check_at = utcnow() + timedelta(minutes=interval)
                await db.commit()
            return

        inv.checks_done += 1

        # IP доступен — дальше проверять смысла нет
        if res.blocked is False:
            if entry is not None:
                await domain_service._apply_result(db, domain, entry, res)  # noqa: SLF001
            domain.status, domain.status_message = DomainStatus.OK, ""
            if not by_speed:
                await _finish(db, inv, S.NOT_BANNED, f"IP {ip} не в бане — открывается из России.")
                return
            if node is not None:
                await db.refresh(node)  # свежая скорость из последнего опроса
            state = _speed_state(node, cfg)
            if state == "recovered":
                await _recovered(db, inv, node, ip, checked=True)
                return
            if state == "unknown":
                await _finish(db, inv, S.NOT_BANNED,
                              f"IP {ip} не в бане. Текущую скорость ноды узнать не удалось.")
                return
            text = (f"{inv.node_name or domain.name}: IP {ip} открывается из России — это не бан, "
                    f"но скорость всё ещё низкая ({_speed_text(node)}). "
                    f"Проверьте сервер ноды и канал у хостера.")
            await _finish(db, inv, S.NOT_BANNED, text)
            await record(db, "node_suspect", "IP не в бане, но скорость ноды низкая", text,
                         level="warning", node=inv.node_name or None, domain=domain.name, ip=ip, emoji="🛠")
            return

        inv.blocked_count += 1
        if inv.checks_done < inv.checks_total:
            inv.next_check_at = utcnow() + timedelta(minutes=interval)
            await db.commit()
            return

        # все проверки показали бан
        if entry is not None:
            await domain_service._apply_result(db, domain, entry, res)  # noqa: SLF001
        auto = domain.auto_switch and bool(cfg["auto_switch_enabled"])
        new_ip = await domain_service.handle_current_banned(db, domain, cache, auto)
        if new_ip:
            summary = f"IP {ip} в бане ({inv.checks_total} из {inv.checks_total}), A-запись сменена на {new_ip}"
        else:
            summary = f"IP {ip} в бане ({inv.checks_total} из {inv.checks_total}). {domain.status_message}"
        await _finish(db, inv, S.BANNED, summary)


async def tick() -> None:
    """Выполнить все проверки, у которых подошло время."""
    async with SessionLocal() as db:
        due = (await db.execute(
            select(Investigation).where(
                Investigation.status == S.ACTIVE, Investigation.next_check_at <= utcnow()
            ).order_by(Investigation.next_check_at)
        )).scalars().all()
        for inv in due:
            try:
                await _step(db, inv)
            except Exception as e:  # noqa: BLE001
                log.exception("Ошибка проверки %s", inv.domain_name)
                await db.rollback()
                await errors.report(db, "investigation", "проверка IP", f"{inv.domain_name}: {e}")


async def cancel(db: AsyncSession, inv: Investigation) -> None:
    await _finish(db, inv, S.CANCELLED, "Отменено вручную")
