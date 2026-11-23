from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import integrations
from app.core.database import get_db
from app.models import Domain, DomainIP, Node
from app.schemas import NodeOut
from app.services import settings_service
from app.services.node_service import get_hidden, hide_node, poll_nodes

router = APIRouter(prefix="/nodes", tags=["nodes"])


ORDER_KEY = "node_order"


class NodeOrderIn(BaseModel):
    uuids: list[str] = Field(default_factory=list, max_length=2000)


async def _list(db: AsyncSession) -> list[NodeOut]:
    domains = {d.name: d for d in (await db.execute(select(Domain))).scalars().all()}
    nodes = (await db.execute(select(Node).order_by(Node.name))).scalars().all()
    # порядок, который пользователь задал перетаскиванием; новые ноды — в конце, по имени
    order = {u: i for i, u in enumerate(await settings_service.get_state(db, ORDER_KEY, []) or [])}
    nodes = sorted(nodes, key=lambda n: (order.get(n.uuid, len(order)), n.name.lower()))
    ip_stats: dict[int, list[int]] = {}  # domain_id → [всего, доступны, в бане, не проверены]
    for domain_id, blocked in (await db.execute(select(DomainIP.domain_id, DomainIP.is_blocked))).all():
        st = ip_stats.setdefault(domain_id, [0, 0, 0, 0])
        st[0] += 1
        st[1 if blocked is False else 2 if blocked is True else 3] += 1
    result = []
    for n in nodes:
        out = NodeOut.model_validate(n)
        d = domains.get(n.address.lower())
        if d:
            out.domain_id, out.domain_status = d.id, d.status
            out.ips_total, out.ips_ok, out.ips_blocked, out.ips_unknown = ip_stats.get(d.id, [0, 0, 0, 0])
        result.append(out)
    return result


@router.get("", response_model=list[NodeOut])
async def list_nodes(db: AsyncSession = Depends(get_db)):
    return await _list(db)


@router.put("/order", response_model=list[NodeOut])
async def save_order(data: NodeOrderIn, db: AsyncSession = Depends(get_db)):
    """Сохранить порядок нод в списке (только в Cheker, Remnawave не трогаем)."""
    seen: set[str] = set()
    uuids = [u for u in data.uuids if not (u in seen or seen.add(u))]
    await settings_service.set_state(db, ORDER_KEY, uuids)
    await db.commit()
    return await _list(db)


def _require_remnawave() -> None:
    if not integrations.remnawave_configured():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Remnawave не настроен (Настройки → Интеграции)")


@router.post("/refresh", response_model=list[NodeOut])
async def refresh_nodes(db: AsyncSession = Depends(get_db)):
    """Обновить текущий список нод (удалённые из Cheker не возвращаются)."""
    _require_remnawave()
    await poll_nodes()
    return await _list(db)


@router.post("/sync")
async def sync_nodes(db: AsyncSession = Depends(get_db)):
    """Синхронизация с Remnawave: вернуть удалённые из Cheker ноды и их домены/IP."""
    _require_remnawave()
    hidden_before = len(await get_hidden(db))
    restored = await poll_nodes(sync=True)
    if restored is None:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Не удалось получить ноды из Remnawave")
    return {"restored": restored, "hidden_before": hidden_before, "nodes": await _list(db)}


@router.delete("/{uuid}")
async def delete_node(uuid: str, db: AsyncSession = Depends(get_db)):
    """Удалить ноду из списка Cheker вместе с её доменом/IP. В Remnawave ничего не меняется."""
    if await db.get(Node, uuid) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нода не найдена")
    deleted_domain = await hide_node(db, uuid)
    return {"ok": True, "deleted_domain": deleted_domain}
