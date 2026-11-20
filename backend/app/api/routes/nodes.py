from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import integrations
from app.core.database import get_db
from app.models import Domain, Node
from app.schemas import NodeOut
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
    if not integrations.remnawave_configured():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Remnawave не настроен (Настройки → Интеграции)")
    await poll_nodes()
    return await _list(db)
