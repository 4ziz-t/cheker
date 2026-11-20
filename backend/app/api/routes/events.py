from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Event
from app.schemas import EventOut, EventsPage
from app.services.settings_service import EVENT_TYPES

router = APIRouter(prefix="/events", tags=["events"])

EXTRA_TYPES = {
    "domain_changed": "Изменения доменов",
    "node_hidden": "Ноды, удалённые из Cheker",
    "node_foreign": "Ноды другой панели Remnawave убраны",
    "node_action": "Действия с нодами (старые версии)",
}


@router.get("", response_model=EventsPage)
async def list_events(
    db: AsyncSession = Depends(get_db),
    type: str | None = None,
    level: str | None = None,
    search: str | None = None,
    domain: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = select(Event)
    if type:
        q = q.where(Event.type.in_(type.split(",")))
    if level:
        q = q.where(Event.level == level)
    if domain:
        q = q.where(Event.domain == domain)
    if search:
        like = f"%{search}%"
        q = q.where(or_(Event.title.ilike(like), Event.message.ilike(like),
                        Event.domain.ilike(like), Event.node.ilike(like), Event.ip.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (await db.execute(q.order_by(Event.id.desc()).limit(limit).offset(offset))).scalars().all()
    return EventsPage(items=[EventOut.model_validate(r) for r in rows], total=total)


@router.get("/types")
async def event_types():
    return {**EVENT_TYPES, **EXTRA_TYPES}
