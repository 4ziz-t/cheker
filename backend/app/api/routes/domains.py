from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.integrations.cloudflare import CloudflareError
from app.models import Domain, DomainIP, Node
from app.models.domain import DomainStatus
from app.schemas import (
    DomainCreate,
    DomainIPsUpdate,
    DomainOut,
    DomainUpdate,
    IpCheckersIn,
    SwitchIn,
    is_ipv4,
)
from app.services import domain_service, node_service
from app.services.events import record

router = APIRouter(prefix="/domains", tags=["domains"])


async def _nodes_by_address(db: AsyncSession) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for n in (await db.execute(select(Node))).scalars().all():
        result.setdefault(n.address.lower(), []).append(n.name)
    return result


def _out(domain: Domain, nodes: dict[str, list[str]]) -> DomainOut:
    out = DomainOut.model_validate(domain)
    out.nodes = nodes.get(domain.name, [])
    return out


async def _get(db: AsyncSession, domain_id: int) -> Domain:
    d = await db.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Домен не найден")
    return d


def _set_ips(domain: Domain, ips: list[str]) -> None:
    """Заменяет пул IP с сохранением статусов уже известных адресов."""
    existing = {e.ip: e for e in domain.ips}
    new_list: list[DomainIP] = []
    for pos, ip in enumerate(ips):
        e = existing.get(ip) or DomainIP(ip=ip)
        e.position = pos
        new_list.append(e)
    domain.ips = new_list


@router.get("", response_model=list[DomainOut])
async def list_domains(db: AsyncSession = Depends(get_db)):
    # домены отключённых в Remnawave нод не показываем
    hidden = await domain_service.hidden_domain_names(db)
    domains = [d for d in (await db.execute(select(Domain))).scalars().all() if d.name not in hidden]
    # домены нод — в порядке нод (как в Remnawave), домены без ноды — после них, по имени
    order = await node_service.domain_order(db)
    domains = sorted(domains, key=lambda d: (order.get(d.name, len(order)), d.name))
    nodes = await _nodes_by_address(db)
    return [_out(d, nodes) for d in domains]


@router.get("/lookup")
async def lookup(name: str = Query(..., min_length=1)):
    """Определить текущий IP домена до добавления (Cloudflare → DNS)."""
    try:
        name = DomainCreate(name=name).name
    except ValidationError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите домен или IPv4-адрес") from e
    if is_ipv4(name):
        return {"name": name, "kind": "ip", "ip": name, "source": "ip"}
    ip, src = await domain_service.detect_current_ip(name)
    return {"name": name, "kind": "domain", "ip": ip, "source": src}


@router.post("", response_model=DomainOut, status_code=201)
async def create_domain(data: DomainCreate, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(Domain).where(Domain.name == data.name))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой домен уже добавлен")
    d, detected, src = await domain_service.create_entry(
        db, data.name, ips=data.ips, auto_switch=data.auto_switch, enabled=data.enabled,
        notes=data.notes, check_port=data.check_port,
    )
    await domain_service.set_ignored(db, d.name, False)
    found = f", текущий IP {detected} ({src})" if detected and d.kind == "domain" else ""
    await record(db, "domain_changed", "Домен добавлен", f"{d.name}, IP в списке: {len(d.ips)}{found}",
                 domain=d.name, notify=False)
    return _out(d, await _nodes_by_address(db))


@router.get("/{domain_id}", response_model=DomainOut)
async def get_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
    return _out(await _get(db, domain_id), await _nodes_by_address(db))


@router.patch("/{domain_id}", response_model=DomainOut)
async def update_domain(domain_id: int, data: DomainUpdate, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        if v is None and k != "check_port":
            continue
        if k == "auto_switch" and d.kind == "ip":
            continue
        setattr(d, k, v)
    await db.commit()
    return _out(d, await _nodes_by_address(db))


@router.put("/{domain_id}/ips", response_model=DomainOut)
async def update_ips(domain_id: int, data: DomainIPsUpdate, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    if d.kind == "ip":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Для записи-IP список адресов не редактируется")
    async with domain_service.domain_lock(d.id):
        before = [e.ip for e in d.ips]
        _set_ips(d, data.ips)
        await db.commit()
        await db.refresh(d)
    added = [ip for ip in data.ips if ip not in before]
    removed = [ip for ip in before if ip not in data.ips]
    if added or removed:
        parts = []
        if added:
            parts.append("добавлены: " + ", ".join(added))
        if removed:
            parts.append("удалены: " + ", ".join(removed))
        await record(db, "domain_changed", "Список IP изменён", f"{d.name}: " + "; ".join(parts),
                     domain=d.name, notify=False)
    return _out(d, await _nodes_by_address(db))


@router.delete("/{domain_id}", status_code=204)
async def delete_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    name = d.name
    await db.delete(d)
    await db.commit()
    # чтобы автоимпорт из Remnawave не добавил его снова
    await domain_service.set_ignored(db, name, True)
    await record(db, "domain_changed", "Домен удалён", f"{name} (A-запись в Cloudflare не тронута)",
                 domain=name, notify=False)


@router.post("/{domain_id}/switch", response_model=DomainOut)
async def switch_domain_ip(domain_id: int, data: SwitchIn, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    if d.kind == "ip":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Это IP-адрес, а не домен: менять нечего")
    if data.ip == d.current_ip:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Этот IP уже назначен")
    async with domain_service.domain_lock(d.id):
        try:
            await domain_service.switch_ip(db, d, data.ip, manual=True, reason="вручную из панели")
        except (CloudflareError, domain_service.DnsConflictError) as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    await db.refresh(d)
    return _out(d, await _nodes_by_address(db))


@router.post("/{domain_id}/ips/check", response_model=DomainOut)
async def check_one_ip(domain_id: int, data: SwitchIn, db: AsyncSession = Depends(get_db)):
    """Проверить один IP из списка (например, резервный) — тратит 1 запрос к чекерам."""
    d = await _get(db, domain_id)
    try:
        await domain_service.check_single_ip(db, d, data.ip)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    d = await db.get(Domain, domain_id, populate_existing=True)
    return _out(d, await _nodes_by_address(db))


@router.put("/{domain_id}/ips/checkers", response_model=DomainOut)
async def set_ip_checkers(domain_id: int, data: IpCheckersIn, db: AsyncSession = Depends(get_db)):
    """Выбрать проверки для одного IP (галочки на странице домена). Новых запросов не тратит."""
    d = await _get(db, domain_id)
    try:
        await domain_service.set_ip_checkers(db, d, data.ip, data.checkers or None)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    db.expunge_all()
    d = await db.get(Domain, domain_id)
    return _out(d, await _nodes_by_address(db))


@router.post("/{domain_id}/check", response_model=DomainOut)
async def check_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    await domain_service.check_now(d.id)
    db.expunge_all()  # проверка шла в своей сессии — читаем домен и его IP заново
    d = await db.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Домен не найден")
    return _out(d, await _nodes_by_address(db))


@router.post("/{domain_id}/check-ips", response_model=DomainOut)
async def check_all_ips(domain_id: int, db: AsyncSession = Depends(get_db)):
    """Проверить все IP домена (текущий и резервные) — кнопка ↻ на вкладке «Ноды»."""
    d = await _get(db, domain_id)
    await domain_service.check_now(d.id, all_ips=True)
    db.expunge_all()  # проверка шла в своей сессии — читаем домен и его IP заново
    d = await db.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Домен не найден")
    return _out(d, await _nodes_by_address(db))


@router.get("/meta/statuses")
async def statuses():
    return {
        DomainStatus.UNKNOWN: "Не проверен",
        DomainStatus.OK: "В порядке",
        DomainStatus.BLOCKED: "IP в бане",
        DomainStatus.NO_IPS: "Нет свободных IP",
        DomainStatus.ERROR: "Ошибка",
        DomainStatus.NO_RECORD: "Нет A-записи",
    }
