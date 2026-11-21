"""Ежедневная сводка."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import utcnow
from app.integrations.telegram import esc
from app.models import Domain, DomainIP, Event, Node
from app.models.domain import DomainStatus
from app.services.events import record


async def build_summary(db: AsyncSession) -> tuple[str, str]:
    nodes = (await db.execute(select(Node))).scalars().all()
    active_nodes = [n for n in nodes if not n.is_disabled]
    offline = [n for n in active_nodes if not n.is_connected]

    domains = (await db.execute(select(Domain).where(Domain.enabled.is_(True)))).scalars().all()
    problems = [d for d in domains if d.status != DomainStatus.OK]
    blocked_ips = (await db.execute(
        select(func.count(func.distinct(DomainIP.ip))).where(DomainIP.is_blocked.is_(True))
    )).scalar_one()

    since = utcnow() - timedelta(hours=24)
    counts = dict((await db.execute(
        select(Event.type, func.count()).where(Event.created_at >= since).group_by(Event.type)
    )).all())

    lines = [
        "📊 <b>Ежедневная сводка</b>",
        "",
        f"🖥 Ноды: {len(active_nodes) - len(offline)}/{len(active_nodes)} online",
    ]
    for n in offline:
        lines.append(f"   🔴 {esc(n.name)} ({esc(n.address)})")
    lines.append(f"🌐 Домены: {len(domains) - len(problems)}/{len(domains)} в порядке")
    for d in problems:
        lines.append(f"   ⚠️ {esc(d.name)} — {esc(d.status_message or d.status)}")
    lines += [
        f"⛔ IP в бане сейчас: {blocked_ips}",
        "",
        "За 24 часа:",
        f"   • новых банов: {counts.get('ip_blocked', 0)}",
        f"   • автосмен IP: {counts.get('ip_switched_auto', 0)}",
        f"   • ручных смен: {counts.get('ip_switched_manual', 0)}",
        f"   • падений нод: {counts.get('node_offline', 0)}",
        f"   • падений скорости: {counts.get('speed_drop', 0)}",
        f"   • «IP не в бане, но скорость низкая»: {counts.get('node_suspect', 0)}",
    ]
    plain = (
        f"Ноды {len(active_nodes) - len(offline)}/{len(active_nodes)} online, "
        f"домены {len(domains) - len(problems)}/{len(domains)} OK, IP в бане: {blocked_ips}"
    )
    return "\n".join(lines), plain


async def send_summary(db: AsyncSession) -> None:
    html_text, plain = await build_summary(db)
    await record(db, "daily_summary", "Ежедневная сводка", plain, tg_text=html_text)
