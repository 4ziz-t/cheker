"""Опрос нод Remnawave и уведомления о смене состояния."""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.tasks import spawn
from app.core.timeutils import fmt_duration, utcnow
from app.integrations.remnawave import RemnaNode, RemnawaveClient, RemnawaveError
from app.models import Domain, DomainIP, Node
from app.models.domain import DomainSource
from app.schemas import DOMAIN_RE, is_ipv4
from app.services import (
    domain_service,
    investigation_service,
    notices,
    settings_service,
)
from app.services.events import errors, record
from app.services.speed import mbps, tracker

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
# uuid → когда по падению скорости/трафика последний раз запускали проверку IP
_drop_handled: dict[str, datetime] = {}
RETRIGGER_AFTER = timedelta(minutes=30)  # падение не прошло — через 30 мин проверить снова
# uuid → сколько опросов подряд ноды нет в ответе Remnawave
_missing: dict[str, int] = {}
GONE_CONFIRM_POLLS = 3
# опросы подряд, в которых в базе снова нашлись ноды чужой панели (признак второго экземпляра Cheker)
_foreign_streak = 0
FOREIGN_WARN_KEY = "foreign_nodes_warned_at"
FOREIGN_WARN_EVERY_SEC = 6 * 3600


def _panel_host(url: str) -> str:
    return urlsplit(url).netloc or url


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
    no_traffic_sec = int(cfg.get("no_traffic_minutes") or 0) * 60
    no_traffic_bytes = float(cfg.get("no_traffic_mb") or 1) * 1_000_000
    triggered: list[tuple[Node, float, float, str | None]] = []

    for rn in remote:
        n = nodes.get(rn.uuid)
        if n is None:
            continue
        if not rn.is_connected or rn.is_disabled:
            # падение у лежащей ноды — это не «бан», о нём и так придёт «нода offline»
            tracker.forget(rn.uuid)
            _drop_handled.pop(rn.uuid, None)
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

        # падение видно сразу: по скорости за последний опрос (а если её нет — по среднему за окно)
        level = n.speed_now_bps if n.speed_now_bps is not None else info.current_bps
        has_norm = info.baseline_bps is not None and info.baseline_bps >= min_base
        dropped = has_norm and level is not None and level <= info.baseline_bps * (1 - drop_share)

        # трафик встал: за последние N минут через ноду прошло меньше X МБ (у ноды, где трафик обычно есть)
        stalled_reason = None
        if has_norm and no_traffic_sec > 0:
            got = tracker.bytes_in(rn.uuid, no_traffic_sec, ts)
            if got is not None and got[1] >= no_traffic_sec * 0.9 and got[0] < no_traffic_bytes:
                stalled_reason = (f"трафик не идёт: за {no_traffic_sec // 60} мин прошло "
                                  f"{got[0] / 1_000_000:.2f} МБ при норме {mbps(info.baseline_bps)}")

        if not dropped and not stalled_reason:
            n.speed_drop_since = None
            _drop_handled.pop(rn.uuid, None)
            continue
        if n.speed_drop_since is None:
            n.speed_drop_since = now
        last = _drop_handled.get(rn.uuid)
        due = last is None or now - last >= RETRIGGER_AFTER
        # скорость ниже нормы держится confirm минут — или трафик встал совсем: проверяем IP
        if due and (stalled_reason or now - n.speed_drop_since >= confirm):
            _drop_handled[rn.uuid] = now
            triggered.append((n, level or 0.0, info.baseline_bps, stalled_reason))
    await tracker.flush(db)
    await db.commit()

    for n, cur, base, why in triggered:
        await investigation_service.on_speed_drop(db, n, cur, base, reason=why)


async def _drop_foreign(db: AsyncSession, existing: dict[str, Node], remote_ids: set[str], panel: str) -> None:
    """Сразу убирает ноды, которых нет в текущей панели и которые пришли из другой панели.

    Так после смены панели Remnawave старые ноды не висят в списке. Если они раз за разом
    появляются снова — в ту же базу пишет ещё один экземпляр Cheker со старыми настройками.
    """
    global _foreign_streak
    if not remote_ids:
        return  # пустой ответ панели — ничего не трогаем
    foreign = [n for uuid, n in existing.items() if uuid not in remote_ids and (n.panel_url or "") != panel]
    if not foreign:
        _foreign_streak = 0
        return
    for n in foreign:
        existing.pop(n.uuid, None)
        _streak.pop(n.uuid, None)
        _missing.pop(n.uuid, None)
        _drop_handled.pop(n.uuid, None)
        tracker.forget(n.uuid)
        await db.delete(n)
    await db.commit()
    names = ", ".join(n.name for n in foreign[:10]) + (" …" if len(foreign) > 10 else "")
    await record(db, "node_foreign", "Убраны ноды другой панели Remnawave",
                 f"Их нет в текущей панели ({_panel_host(panel)}): {names}", level="info", notify=False)

    _foreign_streak += 1
    if _foreign_streak < 2:
        return
    last = float(await settings_service.get_state(db, FOREIGN_WARN_KEY, 0) or 0)
    if time.time() - last < FOREIGN_WARN_EVERY_SEC:
        return
    await settings_service.set_state(db, FOREIGN_WARN_KEY, time.time())
    await db.commit()
    await record(
        db, "integration_error", "Ноды старой панели появляются снова",
        "Cheker убирает ноды, которых нет в текущей панели "
        f"({_panel_host(panel)}), но они снова попадают в базу. Похоже, на сервере запущен ещё один "
        "экземпляр Cheker со старыми настройками и той же папкой data. Проверьте: docker ps -a | grep cheker",
        level="warning", emoji="⚠️",
    )


HIDDEN_KEY = "hidden_nodes"
# свой порядок нод (перетаскивание на вкладке «Ноды»); пустой — порядок как в Remnawave
ORDER_KEY = "node_order"


def _addr(value: str | None) -> str:
    return (value or "").strip().lower().rstrip(".")


async def ordered_nodes(db: AsyncSession) -> list[Node]:
    """Ноды в порядке показа: свой порядок (если задан), иначе — как в панели Remnawave."""
    nodes = (await db.execute(select(Node))).scalars().all()
    order = {u: i for i, u in enumerate(await settings_service.get_state(db, ORDER_KEY, []) or [])}
    return sorted(nodes, key=lambda n: (order.get(n.uuid, len(order)), n.position, n.name.lower()))


async def domain_order(db: AsyncSession) -> dict[str, int]:
    """Адрес домена → место в списке: домены нод идут в порядке нод, остальные — после них."""
    result: dict[str, int] = {}
    for i, n in enumerate(await ordered_nodes(db)):
        result.setdefault(_addr(n.address), i)
    return result


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
    _drop_handled.pop(uuid, None)
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
        panel = RemnawaveClient().base
        await _drop_foreign(db, existing, {rn.uuid for rn in remote_all}, panel)
        confirm = max(int(await settings_service.get(db, "node_offline_confirm_polls")), 1)
        alert_after = timedelta(minutes=max(int(await settings_service.get(db, "node_offline_alert_minutes")), 1))
        repeat_min = int(await settings_service.get(db, "node_offline_repeat_minutes"))
        repeat_every = timedelta(minutes=repeat_min) if repeat_min > 0 else None
        notifications: list[tuple[str, Node]] = []

        new_addresses: set[str] = set()
        for rn in remote:
            n = existing.get(rn.uuid)
            is_new = n is None
            was_disabled = bool(n.is_disabled) if n is not None else False
            if is_new:
                n = Node(uuid=rn.uuid)
                db.add(n)
            # новая нода или нода, которую снова включили в панели, — сразу проверяем её IP
            if (is_new or was_disabled) and not rn.is_disabled and _addr(rn.address):
                new_addresses.add(_addr(rn.address))

            n.panel_url = panel
            n.position = rn.position
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
                # «нода недоступна» — когда не подключена дольше N минут, и дальше каждые M минут
                if now - n.offline_since >= alert_after and (
                    n.offline_alerted_at is None
                    or (repeat_every is not None and now - n.offline_alerted_at >= repeat_every)
                ):
                    n.alert_offline = True
                    n.offline_alerted_at = now
                    notifications.append(("offline", n))
            else:
                if n.alert_offline and count >= confirm:
                    n.alert_offline = False
                    n.offline_alerted_at = None
                    notifications.append(("online", n))
                elif not n.alert_offline:
                    n.offline_since = None  # короткий сбой без уведомления
                    n.offline_alerted_at = None

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

        # отключённые в панели ноды в «Домены» не добавляем
        await _import_addresses(db, [rn for rn in remote if not rn.is_disabled])
        if restored:
            await _import_addresses(db, [rn for rn in restored if not rn.is_disabled], force=True)
            new_addresses |= {_addr(rn.address) for rn in restored if _addr(rn.address) and not rn.is_disabled}
        if sync:
            # синхронизация возвращает порядок нод как в Remnawave
            await settings_service.set_state(db, ORDER_KEY, [])
            await db.commit()
        await _update_speeds(db, remote)

        # новая нода — сразу проверяем все IP её домена на бан (в фоне, опрос не ждёт)
        if new_addresses:
            ids = list((await db.execute(
                select(Domain.id).where(Domain.name.in_(new_addresses), Domain.enabled.is_(True))
            )).scalars().all())
            if ids:
                log.info("Новые ноды: проверяю IP доменов %s", sorted(new_addresses))
                spawn(domain_service.check_many(ids, all_ips=True))

        for kind, n in notifications:
            down = (now - n.offline_since).total_seconds() if n.offline_since else None
            if kind == "offline":
                await record(db, "node_offline", "Нода недоступна",
                             f"{_node_label(n)}\nНе подключена {fmt_duration(down or 0)}",
                             level="error", node=n.name, tg_text=notices.node_down(n, down or 0))
            else:
                n.offline_since = None
                await db.commit()
                downtime = f"\nБыла недоступна {fmt_duration(down)}" if down else ""
                await record(db, "node_online", "Нода снова на связи", f"{_node_label(n)}{downtime}",
                             level="success", node=n.name, tg_text=notices.node_up(n, down))
        return len(restored)
