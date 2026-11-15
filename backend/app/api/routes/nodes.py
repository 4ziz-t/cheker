from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.integrations.remnawave import RemnawaveClient, RemnawaveError
from app.models import Domain, Node
from app.schemas import NodeOut
from app.services.events import record
from app.services.node_service import poll_nodes

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


@router.post("/refresh", response_model=list[NodeOut])
async def refresh_nodes(db: AsyncSession = Depends(get_db)):
    if not get_settings().remnawave_configured:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Remnawave не настроен в .env")
    await poll_nodes()
    return await _list(db)


ACTIONS = {"restart": "перезапущена", "enable": "включена", "disable": "отключена"}


@router.post("/{uuid}/{action}")
async def node_action(uuid: str, action: str, db: AsyncSession = Depends(get_db)):
    if action not in ACTIONS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Неизвестное действие")
    node = await db.get(Node, uuid)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нода не найдена")
    client = RemnawaveClient()
    try:
        await getattr(client, f"{action}_node")(uuid)
    except RemnawaveError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    await record(db, "node_action", f"Нода {ACTIONS[action]}", f"{node.name} ({node.address})",
                 node=node.name, notify=False)
    return {"ok": True}
