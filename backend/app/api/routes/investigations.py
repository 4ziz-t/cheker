from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Domain, Investigation
from app.models.investigation import InvestigationStatus
from app.schemas import InvestigationOut
from app.services import investigation_service
from app.services.scheduler import scheduler

router = APIRouter(tags=["investigations"])


@router.get("/investigations", response_model=list[InvestigationOut])
async def list_investigations(
    db: AsyncSession = Depends(get_db),
    domain_id: int | None = None,
    active: bool | None = None,
    limit: int = Query(30, ge=1, le=200),
):
    q = select(Investigation)
    if domain_id is not None:
        q = q.where(Investigation.domain_id == domain_id)
    if active is True:
        q = q.where(Investigation.status == InvestigationStatus.ACTIVE)
    rows = (await db.execute(q.order_by(Investigation.id.desc()).limit(limit))).scalars().all()
    return [InvestigationOut.model_validate(r) for r in rows]


@router.post("/domains/{domain_id}/investigate", response_model=InvestigationOut)
async def start_investigation(domain_id: int, db: AsyncSession = Depends(get_db)):
    """Запустить проверку вручную (N раз с интервалом), как при падении скорости."""
    d = await db.get(Domain, domain_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Домен не найден")
    inv = await investigation_service.start(db, d, reason="запущено вручную", force=True)
    if inv is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Проверка этого домена уже идёт")
    scheduler.wake_investigations()
    return InvestigationOut.model_validate(inv)


@router.post("/investigations/{inv_id}/cancel", response_model=InvestigationOut)
async def cancel_investigation(inv_id: int, db: AsyncSession = Depends(get_db)):
    inv = await db.get(Investigation, inv_id)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проверка не найдена")
    if inv.status != InvestigationStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Проверка уже завершена")
    await investigation_service.cancel(db, inv)
    return InvestigationOut.model_validate(inv)
