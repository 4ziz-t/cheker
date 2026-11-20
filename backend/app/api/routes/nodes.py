from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import integrations
from app.core.database import get_db
from app.models import Domain, Node
from app.schemas import NodeOut
from app.services.node_service import get_hidden, hide_node, poll_nodes

router = APIRouter(prefix="/nodes", tags=["nodes"])


async def _list(db: AsyncSession) -> list[NodeOut]:
    domains = {d.name: d for d in (await db.execute(select(Domain))).scalars().all()}
    nodes = (await db.execute(select(Node).order_by(Node.name))).scalars().all()
    result = []
    for n in nodes:
        out = NodeOut.model_validate(n)
        d = domains.get(n.address.lower())
        if d:
            out.domain_id, out.domain_status = d.id, d.status
        result.append(out)
    return result


@router.get("", response_model=list[NodeOut])
async def list_nodes(db: AsyncSession = Depends(get_db)):
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
