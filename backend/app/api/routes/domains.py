from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.tasks import spawn
from app.integrations.cloudflare import CloudflareError
from app.models import Domain, DomainIP, Node
from app.models.domain import DomainStatus
from app.schemas import DomainCreate, DomainIPsUpdate, DomainOut, DomainUpdate, SwitchIn
from app.services import domain_service
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


def _check_in_background(domain_id: int) -> None:
    spawn(domain_service.run_cycle([domain_id]))


@router.get("", response_model=list[DomainOut])
async def list_domains(db: AsyncSession = Depends(get_db)):
    domains = (await db.execute(select(Domain).order_by(Domain.name))).scalars().all()
    nodes = await _nodes_by_address(db)
    return [_out(d, nodes) for d in domains]


@router.post("", response_model=DomainOut, status_code=201)
async def create_domain(data: DomainCreate, db: AsyncSession = Depends(get_db)):
    if (await db.execute(select(Domain).where(Domain.name == data.name))).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Такой домен уже добавлен")
    d = Domain(name=data.name, auto_switch=data.auto_switch, enabled=data.enabled, notes=data.notes)
    _set_ips(d, data.ips)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    await record(db, "domain_changed", "Домен добавлен", f"{d.name}, IP: {len(data.ips)}",
                 domain=d.name, notify=False)
    if d.enabled:
        _check_in_background(d.id)
    return _out(d, await _nodes_by_address(db))


@router.get("/{domain_id}", response_model=DomainOut)
async def get_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
    return _out(await _get(db, domain_id), await _nodes_by_address(db))


@router.patch("/{domain_id}", response_model=DomainOut)
async def update_domain(domain_id: int, data: DomainUpdate, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(d, k, v)
    await db.commit()
    return _out(d, await _nodes_by_address(db))


@router.put("/{domain_id}/ips", response_model=DomainOut)
async def update_ips(domain_id: int, data: DomainIPsUpdate, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
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
        if added and d.enabled:
            _check_in_background(d.id)
    return _out(d, await _nodes_by_address(db))


@router.delete("/{domain_id}", status_code=204)
async def delete_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    name = d.name
    await db.delete(d)
    await db.commit()
    await record(db, "domain_changed", "Домен удалён", f"{name} (A-запись в Cloudflare не тронута)",
                 domain=name, notify=False)


@router.post("/{domain_id}/switch", response_model=DomainOut)
async def switch_domain_ip(domain_id: int, data: SwitchIn, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    if data.ip == d.current_ip:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Этот IP уже назначен")
    async with domain_service.domain_lock(d.id):
        try:
            await domain_service.switch_ip(db, d, data.ip, manual=True, reason="вручную из панели")
        except (CloudflareError, domain_service.DnsConflictError) as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    await db.refresh(d)
    return _out(d, await _nodes_by_address(db))


@router.post("/{domain_id}/check", response_model=DomainOut)
async def check_domain(domain_id: int, db: AsyncSession = Depends(get_db)):
    d = await _get(db, domain_id)
    await domain_service.run_cycle([d.id])
    d = await db.get(Domain, domain_id, populate_existing=True)
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
