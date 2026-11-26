"""Тексты уведомлений в Telegram (HTML). Один формат для всех мест, где они отправляются."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import fmt_duration
from app.integrations.telegram import esc
from app.models import Domain, Node


def _addr(value: str | None) -> str:
    return (value or "").strip().lower().rstrip(".")


async def node_name(db: AsyncSession, address: str) -> str:
    """«Au-1 ZET (AT)» — имя ноды(нод) с этим адресом вместе со страной."""
    nodes = (await db.execute(select(Node).where(Node.is_disabled.is_(False)))).scalars().all()
    names = [
        f"{n.name} ({n.country_code})" if n.country_code else n.name
        for n in nodes
        if _addr(n.address) == _addr(address)
    ]
    return ", ".join(names) or "—"


def ip_counts(domain: Domain) -> tuple[int, int]:
    """(живых, всего) IP в списке домена."""
    return sum(1 for e in domain.ips if e.is_blocked is False), len(domain.ips)


def _head(emoji: str, title: str) -> str:
    return f"{emoji} <b>{esc(title)}</b>"


async def switched(db: AsyncSession, domain: Domain, old_ip: str | None, new_ip: str) -> str:
    """✅ Замена — IP в бане, A-запись переключена на живой."""
    alive, total = ip_counts(domain)
    spare = max(alive - 1, 0)  # живые, кроме нового текущего
    unchecked = sum(1 for e in domain.ips if e.is_blocked is None)
    tail = "все IP проверены" if not unchecked else f"не проверено IP: {unchecked}"
    return "\n".join([
        _head("✅", "Замена"),
        f"Имя: {esc(await node_name(db, domain.name))}",
        f"Адрес: <code>{esc(domain.name)}</code>",
        f"Замена IP: с <code>{esc(old_ip or '—')}</code> на <code>{esc(new_ip)}</code>",
        f"Живых IP: {alive}/{total}",
        f"Статус: осталось запасных IP — {spare} ({tail})",
    ])


async def banned_no_ips(db: AsyncSession, domain: Domain) -> str:
    """🛑 Бан без замены — живых IP не осталось."""
    alive, total = ip_counts(domain)
    return "\n".join([
        _head("🛑", "Бан без замены"),
        f"Имя: {esc(await node_name(db, domain.name))}",
        f"Адрес: <code>{esc(domain.name)}</code>",
        "Замена IP: нет живых IP",
        f"Живых IP: {alive}/{total}",
        "Статус: нода заблокирована, добавьте IP",
    ])


async def banned_no_switch(db: AsyncSession, domain: Domain, reason: str) -> str:
    """🟡 Нода забанена — сменить IP нельзя (автосмена выключена, нет API и т.п.)."""
    alive, total = ip_counts(domain)
    return "\n".join([
        _head("🟡", "Нода забанена"),
        f"Имя: {esc(await node_name(db, domain.name))}",
        f"Адрес: <code>{esc(domain.name)}</code>",
        f"IP в бане: <code>{esc(domain.current_ip or domain.name)}</code>",
        f"Живых IP: {alive}/{total}",
        f"Статус: {esc(reason)}",
    ])


async def speed_problem(db: AsyncSession, domain: Domain, ips: list[str], speed: str = "") -> str:
    """Ⓜ️ Проблемы со скоростью — IP не в бане, но трафик не идёт. Одно сообщение: падение + итог."""
    lines = [
        _head("Ⓜ️", "Проблемы со скоростью"),
        f"Нода: {esc(await node_name(db, domain.name))}",
        f"Домен: <code>{esc(domain.name)}</code>",
        f"IP: {', '.join(f'<code>{esc(ip)}</code>' for ip in ips) or '—'}",
    ]
    if speed:
        lines.append(f"Скорость: {esc(speed)}")
    lines += [
        "",
        "Статус: IP не забанен, но трафик и скорость перестали идти.",
        "Возможно, упала выходящая нода.",
    ]
    return "\n".join(lines)


async def speed_check_failed(db: AsyncSession, domain: Domain, ip: str, speed: str, error: str) -> str:
    """⚠️ Скорость упала, а проверить IP не удалось (источники не ответили)."""
    lines = [
        _head("⚠️", "Скорость упала, проверить IP не удалось"),
        f"Нода: {esc(await node_name(db, domain.name))}",
        f"Домен: <code>{esc(domain.name)}</code>",
        f"IP: <code>{esc(ip)}</code>",
    ]
    if speed:
        lines.append(f"Скорость: {esc(speed)}")
    lines.append(f"Ошибка: {esc(error or '—')}")
    return "\n".join(lines)


def node_down(n: Node, down_seconds: float) -> str:
    lines = [
        _head("🔴", "Нода недоступна!"),
        f"📍 Имя: {esc(n.name)}",
    ]
    if n.country_code:
        lines.append(f"🌍 Страна: {esc(n.country_code)}")
    lines += [
        f"🖥 Адрес: <code>{esc(n.address)}</code>",
        f"⏱️ Не подключена {fmt_duration(down_seconds)}",
    ]
    if n.last_status_message:
        lines.append(f"ℹ️ {esc(n.last_status_message)}")
    return "\n".join(lines)


def node_up(n: Node, down_seconds: float | None) -> str:
    lines = [
        _head("🟢", "Нода снова на связи"),
        f"📍 Имя: {esc(n.name)}",
    ]
    if n.country_code:
        lines.append(f"🌍 Страна: {esc(n.country_code)}")
    lines.append(f"🖥 Адрес: <code>{esc(n.address)}</code>")
    if down_seconds:
        lines.append(f"⏱️ Была недоступна {fmt_duration(down_seconds)}")
    return "\n".join(lines)
