"""Опрос нод Remnawave и уведомления о смене состояния."""
import asyncio
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.core.tasks import spawn
from app.core.timeutils import fmt_duration, utcnow
from app.integrations.remnawave import RemnaNode, RemnawaveClient, RemnawaveError
from app.models import Domain, DomainIP, Node
from app.models.domain import DomainSource
from app.schemas import DOMAIN_RE, is_ipv4
from app.services import domain_service, settings_service
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
        spawn(domain_service.run_cycle([d.id]))


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
