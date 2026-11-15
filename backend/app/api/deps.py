from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import COOKIE_NAME, get_session
from app.models import UserSession


async def require_auth(request: Request, db: AsyncSession = Depends(get_db)) -> UserSession:
    sess = await get_session(db, request.cookies.get(COOKIE_NAME))
    if sess is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход")
    return sess
