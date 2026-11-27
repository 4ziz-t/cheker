"""Ежедневный отчёт по нодам (по умолчанию в 07:00)."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import utcnow
from app.integrations.telegram import esc
from app.models import Domain, Event
from app.services import settings_service
from app.services.events import record

ONE_ALIVE_KEY = "summary_one_alive"  # домены с одним живым IP на момент прошлого отчёта


def _addr(value: str | None) -> str:
    return (value or "").strip().lower().rstrip(".")


async def build_summary(
    db: AsyncSession, save: bool = False, sweep: dict | None = None, sweep_seconds: float = 0
) -> tuple[str, str]:
    """save — запомнить список «один живой IP», чтобы в следующий раз показать новые.

    sweep — итоги проверки всех IP через Red Atlas (id домена → DomainStat), если она была.
    """
    from app.services.domain_service import (
        hidden_domain_names,  # локально: без цикла импортов
    )
    from app.services.node_service import ordered_nodes

    nodes = [n for n in await ordered_nodes(db) if not n.is_disabled]
    online = [n for n in nodes if n.is_connected]
    offline = [n for n in nodes if not n.is_connected]

    hidden = await hidden_domain_names(db)
    domains = {
        d.name: d
        for d in (await db.execute(select(Domain).where(Domain.enabled.is_(True)))).scalars().all()
        if d.name not in hidden
    }

    def current_ok(name: str) -> bool | None:
        d = domains.get(_addr(name))
        if d is None:
            return None
        entry = next((e for e in d.ips if e.ip == d.current_ip), None)
        return None if entry is None else entry.is_blocked is False

    # «в строю» — нода подключена к панели и её текущий IP не в бане
    healthy = [n for n in online if current_ok(n.address) is not False]

    # домены в порядке нод (как в Remnawave), затем остальные по имени
    ordered: list[tuple[Domain, str]] = []
    seen: set[str] = set()
    for n in nodes:
        d = domains.get(_addr(n.address))
        if d and d.name not in seen:
            seen.add(d.name)
            label = f"{n.name} ({n.country_code})" if n.country_code else n.name
            ordered.append((d, label))
    ordered += [(d, "") for name, d in sorted(domains.items()) if name not in seen]

    def alive(d: Domain) -> tuple[int, int]:
        return sum(1 for e in d.ips if e.is_blocked is False), len(d.ips)

    one_alive = [(d, label) for d, label in ordered if alive(d)[0] == 1]
    none_alive = [(d, label) for d, label in ordered if d.ips and alive(d)[0] == 0]
    previous = set(await settings_service.get_state(db, ONE_ALIVE_KEY, []) or [])
    new_one = [(d, label) for d, label in one_alive if d.name not in previous]

    since = utcnow() - timedelta(hours=24)
    counts = dict((await db.execute(
        select(Event.type, func.count()).where(Event.created_at >= since).group_by(Event.type)
    )).all())
    switches = counts.get("ip_switched_auto", 0)
    manual = counts.get("ip_switched_manual", 0)

    def row(d: Domain, label: str) -> str:
        a, t = alive(d)
        who = f" — {esc(label)}" if label else ""
        return f"   • <code>{esc(d.name)}</code>{who} · {a}/{t}"

    lines = [
        "📊 <b>Отчёт по нодам</b>",
        "",
        f"🟢 Ноды в строю: <b>{len(healthy)}/{len(nodes)}</b> (подключены к панели и IP не в бане)",
    ]
    if offline:
        lines.append(f"🔴 Не подключены: {len(offline)}")
        lines += [f"   • {esc(n.name)} (<code>{esc(n.address)}</code>)" for n in offline]
    lines.append(f"🔁 Замен IP за сутки: <b>{switches}</b>" + (f" (+ вручную: {manual})" if manual else ""))
    lines.append("")
    if one_alive:
        lines.append(f"⚠️ Остался один живой IP ({len(one_alive)}):")
        lines += [row(d, label) for d, label in one_alive]
    else:
        lines.append("✅ Нод с одним живым IP нет")
    if new_one:
        lines.append("")
        lines.append(f"🆕 Новые (за сутки, остался 1 живой IP): {len(new_one)}")
        lines += [row(d, label) for d, label in new_one]
    if none_alive:
        lines.append("")
        lines.append(f"🛑 Нет живых IP ({len(none_alive)}):")
        lines += [row(d, label) for d, label in none_alive]

    if sweep:
        by_id = {d.id: (d, label) for d, label in ordered}
        rows = [(by_id[i][0], by_id[i][1], st) for i, st in sweep.items() if i in by_id]
        rows.sort(key=lambda x: [d.name for d, _ in ordered].index(x[0].name))
        total_ok = sum(st.ok for *_, st in rows)
        total_banned = sum(st.banned for *_, st in rows)
        total_unknown = sum(st.unknown for *_, st in rows)
        minutes = max(round(sweep_seconds / 60), 1)
        lines += ["", f"🔎 <b>Проверка всех IP (Red Atlas)</b> — {minutes} мин",
                  f"✅ Живых: {total_ok} · ⛔ В бане: {total_banned}"
                  + (f" · ❔ Не проверено: {total_unknown}" if total_unknown else "")]
        for d, label, st in rows:
            who = esc(label) if label else "без ноды"
            mark = "🔴" if st.current_banned else ("🟡" if st.banned else "🟢")
            extra = f" · ❔ {st.unknown}" if st.unknown else ""
            lines.append(f"{mark} {who} — <code>{esc(d.name)}</code>: ✅ {st.ok} · ⛔ {st.banned}{extra}")

    if save:
        await settings_service.set_state(db, ONE_ALIVE_KEY, [d.name for d, _ in one_alive])
        await db.commit()

    plain = (
        f"Ноды в строю {len(healthy)}/{len(nodes)}, замен за сутки: {switches}, "
        f"один живой IP: {len(one_alive)}, нет живых IP: {len(none_alive)}"
    )
    return "\n".join(lines), plain


async def send_summary(db: AsyncSession, sweep: dict | None = None, sweep_seconds: float = 0) -> None:
    html_text, plain = await build_summary(db, save=True, sweep=sweep, sweep_seconds=sweep_seconds)
    await record(db, "daily_summary", "Отчёт по нодам", plain, tg_text=html_text)
