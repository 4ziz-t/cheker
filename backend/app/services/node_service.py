"""Опрос нод Remnawave и уведомления о смене состояния."""
import asyncio
import logging
import time
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.timeutils import fmt_duration, utcnow
from app.integrations.remnawave import RemnaNode, RemnawaveClient, RemnawaveError
from app.models import Domain, DomainIP, Node
from app.models.domain import DomainSource
from app.schemas import DOMAIN_RE, is_ipv4
from app.services import domain_service, investigation_service, settings_service
from app.services.speed import tracker
from app.services.events import errors, record

log = logging.getLogger(__name__)
_poll_lock = asyncio.Lock()


def _node_label(n: Node) -> str:
    flag = f"[{n.country_code}] " if n.country_code else ""
    return f"{flag}{n.name} ({n.address})"


async def _import_addresses(db: AsyncSession, remote: list[RemnaNode], force: bool = False) -> None:
    """Добавляет адреса нод (домен или IP) во вкладку «Домены», если их там ещё нет.

    force — добавить даже при выключенном автоимпорте (синхронизация с Remnawave).
    """
    if not force and not await settings_service.get(db, "auto_import_nodes"):
        return
    ignored = set(await domain_service.get_ignored(db))
    names = set((await db.execute(select(Domain.name))).scalars().all())
    pool_ips = set((await db.execute(select(DomainIP.ip))).scalars().all())

    by_addr: dict[str, list[str]] = {}
    for rn in remote:
        addr = (rn.address or "").strip().lower().rstrip(".")
        if addr:
            by_addr.setdefault(addr, []).append(rn.name)

    for addr, node_names in sorted(by_addr.items()):
        if addr in names or addr in ignored:
            continue
        ip_addr = is_ipv4(addr)
        if ip_addr and addr in pool_ips:
            continue  # этот IP уже проверяется в составе какого-то домена
        if not ip_addr and not DOMAIN_RE.match(addr):
            continue
        try:
            d, detected, _ = await domain_service.create_entry(
                db, addr, source=DomainSource.REMNAWAVE, notes="Нода: " + ", ".join(node_names),
            )
        except Exception:  # noqa: BLE001
            await db.rollback()
            log.exception("Не удалось добавить %s из Remnawave", addr)
            continue
        names.add(addr)
        what = "IP" if ip_addr else "Домен"
        extra = f", текущий IP {detected}" if detected and not ip_addr else ""
        await record(db, "domain_imported", f"{what} добавлен из Remnawave",
                     f"{addr} — нода {', '.join(node_names)}{extra}", domain=addr, emoji="➕")


REALTIME_RECHECK_SEC = 3600
# uuid → (состояние up/down, сколько опросов подряд)
_streak: dict[str, tuple[str, int]] = {}
# ноды, по текущему падению скорости которых уже приняты меры (сбрасывается, когда скорость вернулась)
_drop_handled: set[str] = set()
# uuid → сколько опросов подряд ноды нет в ответе Remnawave
_missing: dict[str, int] = {}
GONE_CONFIRM_POLLS = 3


async def _update_speeds(db: AsyncSession, remote: list[RemnaNode]) -> None:
    """Обновляет скорость нод и запускает проверку IP, если скорость упала."""
    cfg = await settings_service.get_all(db)
    ts = time.time()

    # realtime-скорость из панели (если поддерживается); иначе — прирост trafficUsedBytes
    speeds = None
    if tracker.realtime_supported is not False or ts - tracker.realtime_checked_at > REALTIME_RECHECK_SEC:
        speeds = await RemnawaveClient().get_realtime_speeds()
        tracker.realtime_supported = speeds is not None
        tracker.realtime_checked_at = ts

    nodes = {n.uuid: n for n in (await db.execute(select(Node))).scalars().all()}
    now = utcnow()
    drop_share = float(cfg["speed_drop_percent"]) / 100
    min_base = float(cfg["speed_min_baseline_mbps"]) * 1_000_000 / 8
    confirm = timedelta(minutes=int(cfg["speed_confirm_minutes"]))
    triggered: list[tuple[Node, float, float]] = []

    for rn in remote:
        n = nodes.get(rn.uuid)
        if n is None:
            continue
        if not rn.is_connected or rn.is_disabled:
            # падение у лежащей ноды — это не «бан», о нём и так придёт «нода offline»
            tracker.forget(rn.uuid)
            _drop_handled.discard(rn.uuid)
            n.speed_bps = n.baseline_bps = n.speed_now_bps = None
            n.speed_drop_since = None
            continue
        if speeds is not None and rn.uuid in speeds:
            tracker.add_speed(rn.uuid, speeds[rn.uuid], ts)
            n.speed_source = "realtime"
        elif rn.traffic_used_bytes is not None:
            tracker.add_counter(rn.uuid, rn.traffic_used_bytes, ts)
            n.speed_source = "counter"
        else:
            n.speed_source = None

        info = tracker.info(rn.uuid, int(cfg["speed_window_minutes"]), int(cfg["speed_baseline_hours"]), ts)
        n.speed_bps = int(info.current_bps) if info.current_bps is not None else None
        n.baseline_bps = int(info.baseline_bps) if info.baseline_bps is not None else None
        n.speed_now_bps = int(info.now_bps) if info.now_bps is not None else None
        if speeds is not None and rn.uuid in speeds:
            n.speed_now_bps = int(speeds[rn.uuid])  # realtime — самое точное «сейчас»

        dropped = (
            info.current_bps is not None and info.baseline_bps is not None
            and info.baseline_bps >= min_base
            and info.current_bps <= info.baseline_bps * (1 - drop_share)
        )
        if not dropped:
            n.speed_drop_since = None
            _drop_handled.discard(rn.uuid)
            continue
        if n.speed_drop_since is None:
            n.speed_drop_since = now
        if now - n.speed_drop_since >= confirm and rn.uuid not in _drop_handled:
            _drop_handled.add(rn.uuid)
            triggered.append((n, info.current_bps, info.baseline_bps))
    await tracker.flush(db)
    await db.commit()

    for n, cur, base in triggered:
        await investigation_service.on_speed_drop(db, n, cur, base)


HIDDEN_KEY = "hidden_nodes"


async def get_hidden(db: AsyncSession) -> list[str]:
    """uuid нод, удалённых из списка Cheker (в Remnawave они остаются)."""
    return list(await settings_service.get_state(db, HIDDEN_KEY, []))


async def hide_node(db: AsyncSession, uuid: str) -> str | None:
    """Удаляет ноду из списка Cheker вместе с её доменом/IP. В Remnawave ничего не меняется.

    Возвращает имя удалённого домена (если был).
    """
    node = await db.get(Node, uuid)
    if node is None:
        return None
    hidden = set(await get_hidden(db))
    hidden.add(uuid)
    await settings_service.set_state(db, HIDDEN_KEY, sorted(hidden))

    address = (node.address or "").strip().lower().rstrip(".")
    name = node.name
    await db.delete(node)
    tracker.forget(uuid)
    await tracker.flush(db)
    _streak.pop(uuid, None)
    _drop_handled.discard(uuid)
    await db.commit()

    deleted_domain = None
    if address:
        # домен удаляем, только если его не использует другая нода из списка
        others = (await db.execute(select(Node.uuid).where(Node.address.ilike(address)))).first()
        domain = (await db.execute(select(Domain).where(Domain.name == address))).scalar_one_or_none()
        if domain is not None and others is None:
            deleted_domain = domain.name
            await db.delete(domain)
            await db.commit()
        # чтобы автоимпорт не вернул домен, пока нода удалена
        await domain_service.set_ignored(db, address, True)

    await record(db, "node_hidden", "Нода удалена из Cheker",
                 f"{name} ({address})" + (f", удалён домен/IP {deleted_domain}" if deleted_domain else "")
                 + ". В Remnawave ничего не менялось.", node=name, notify=False)
    return deleted_domain


async def poll_nodes(sync: bool = False) -> int | None:
    """Опрос нод. sync=True — вернуть удалённые из списка ноды (и их домены).

    Возвращает число восстановленных нод (для sync) или 0; None — если опрос не удался/уже идёт.
    """
    if _poll_lock.locked() and not sync:
        return None  # обычный опрос уже идёт; синхронизация — дождётся его
    async with _poll_lock, SessionLocal() as db:
        try:
            remote_all = await RemnawaveClient().get_nodes()
            await errors.resolve(db, "remnawave", "Remnawave")
        except RemnawaveError as e:
            await errors.report(db, "remnawave", "Remnawave", str(e))
            return None

        hidden = set(await get_hidden(db))
        restored: list[RemnaNode] = []
        if sync and hidden:
            restored = [rn for rn in remote_all if rn.uuid in hidden]
            await settings_service.set_state(db, HIDDEN_KEY, [])
            for rn in restored:
                addr = (rn.address or "").strip().lower().rstrip(".")
                if addr:
                    await domain_service.set_ignored(db, addr, False)
            hidden = set()
            await db.commit()
        remote = [rn for rn in remote_all if rn.uuid not in hidden]

        existing = {n.uuid: n for n in (await db.execute(select(Node))).scalars().all()}
        now = utcnow()
        confirm = max(int(await settings_service.get(db, "node_offline_confirm_polls")), 1)
        notifications: list[tuple[str, Node]] = []

        for rn in remote:
            n = existing.get(rn.uuid)
            is_new = n is None
            if is_new:
                n = Node(uuid=rn.uuid)
                db.add(n)

            n.name, n.address, n.port = rn.name, rn.address, rn.port
            n.country_code = rn.country_code
            n.is_connected, n.is_disabled, n.is_connecting = rn.is_connected, rn.is_disabled, rn.is_connecting
            n.users_online, n.xray_version = rn.users_online, rn.xray_version
            n.last_status_message = rn.last_status_message
            n.updated_at = now

            if rn.is_disabled:
                # отключили вручную в панели — это не авария
                n.offline_since = None
                n.alert_offline = False
                _streak.pop(rn.uuid, None)
                continue

            # сколько опросов подряд нода в одном состоянии (защита от «мигания» статуса)
            state = "up" if rn.is_connected else "down"
            prev_state, count = _streak.get(rn.uuid, (state, 0))
            count = count + 1 if prev_state == state else 1
            _streak[rn.uuid] = (state, count)

            if state == "down":
                if n.offline_since is None:
                    n.offline_since = now
                if not n.alert_offline and count >= confirm:
                    n.alert_offline = True
                    notifications.append(("offline", n))
            else:
                if n.alert_offline and count >= confirm:
                    n.alert_offline = False
                    notifications.append(("online", n))
                elif not n.alert_offline:
                    n.offline_since = None  # короткий сбой без уведомления

        # ноду удаляем из списка, только если её нет в ответе Remnawave несколько опросов подряд:
        # панель иногда отдаёт неполный/пустой список, и тогда все ноды «пропадали»
        remote_ids = {rn.uuid for rn in remote_all}
        gone = []
        if remote_all:
            for uuid in existing:
                if uuid in remote_ids or uuid in hidden:
                    _missing.pop(uuid, None)
                    continue
                _missing[uuid] = _missing.get(uuid, 0) + 1
                if _missing[uuid] >= GONE_CONFIRM_POLLS:
                    gone.append(uuid)
        elif existing:
            log.warning("Remnawave вернул пустой список нод — список в Cheker не трогаю")
        for uuid in gone:
            _missing.pop(uuid, None)
            _streak.pop(uuid, None)
            tracker.forget(uuid)
        if gone:
            await db.execute(delete(Node).where(Node.uuid.in_(gone)))
        await db.commit()

        await _import_addresses(db, remote)
        if restored:
            await _import_addresses(db, restored, force=True)
        await _update_speeds(db, remote)

        for kind, n in notifications:
            if kind == "offline":
                reason = f"\nСтатус: {n.last_status_message}" if n.last_status_message else ""
                await record(db, "node_offline", "Нода offline", f"{_node_label(n)}{reason}",
                             level="error", node=n.name, emoji="🔴")
            else:
                downtime = ""
                if n.offline_since:
                    downtime = f"\nНе работала: {fmt_duration((now - n.offline_since).total_seconds())}"
                n.offline_since = None
                await db.commit()
                await record(db, "node_online", "Нода снова online", f"{_node_label(n)}{downtime}",
                             level="success", node=n.name, emoji="🟢")
        return len(restored)
