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


async def _import_addresses(db: AsyncSession, remote: list[RemnaNode]) -> None:
    """Добавляет адреса нод (домен или IP) во вкладку «Домены», если их там ещё нет."""
    if not await settings_service.get(db, "auto_import_nodes"):
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
# ноды, по текущему падению скорости которых уже приняты меры (сбрасывается, когда скорость вернулась)
_drop_handled: set[str] = set()


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
            n.speed_bps = n.baseline_bps = None
            n.speed_drop_since = None
            continue
        if speeds is not None and rn.uuid in speeds:
            tracker.add_speed(rn.uuid, speeds[rn.uuid], ts)
        elif rn.traffic_used_bytes is not None:
            tracker.add_counter(rn.uuid, rn.traffic_used_bytes, ts)

        info = tracker.info(rn.uuid, int(cfg["speed_window_minutes"]), int(cfg["speed_baseline_hours"]), ts)
        n.speed_bps = int(info.current_bps) if info.current_bps is not None else None
        n.baseline_bps = int(info.baseline_bps) if info.baseline_bps is not None else None

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
    await db.commit()

    for n, cur, base in triggered:
        await investigation_service.on_speed_drop(db, n, cur, base)


async def poll_nodes() -> bool:
    if _poll_lock.locked():
        return False
    async with _poll_lock, SessionLocal() as db:
        try:
            remote = await RemnawaveClient().get_nodes()
            await errors.resolve(db, "remnawave", "Remnawave")
        except RemnawaveError as e:
            await errors.report(db, "remnawave", "Remnawave", str(e))
            return False

        existing = {n.uuid: n for n in (await db.execute(select(Node))).scalars().all()}
        now = utcnow()
        notifications: list[tuple[str, Node]] = []

        for rn in remote:
            n = existing.get(rn.uuid)
            is_new = n is None
            if is_new:
                n = Node(uuid=rn.uuid)
                db.add(n)
            prev_connected = n.is_connected

            n.name, n.address, n.port = rn.name, rn.address, rn.port
            n.country_code = rn.country_code
            n.is_connected, n.is_disabled, n.is_connecting = rn.is_connected, rn.is_disabled, rn.is_connecting
            n.users_online, n.xray_version = rn.users_online, rn.xray_version
            n.last_status_message = rn.last_status_message
            n.updated_at = now

            if rn.is_disabled:
                n.offline_since = None
                continue
            if not rn.is_connected and (is_new or prev_connected):
                n.offline_since = now
                notifications.append(("offline", n))
            elif rn.is_connected and not prev_connected and not is_new:
                notifications.append(("online", n))

        remote_ids = {rn.uuid for rn in remote}
        gone = [uuid for uuid in existing if uuid not in remote_ids]
        if gone:
            await db.execute(delete(Node).where(Node.uuid.in_(gone)))
        await db.commit()

        await _import_addresses(db, remote)
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
        return True
