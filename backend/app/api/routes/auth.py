import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_auth
from app.core import security
from app.core.config import get_settings
from app.core.database import get_db
from app.schemas import LoginIn
from app.services.events import record

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(data: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    ip = security.client_ip(request)
    wait = await security.lock_remaining(db, ip)
    if wait:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"Слишком много попыток. Повторите через {wait // 60 + 1} мин.")

    if not security.check_password(data.password):
        await asyncio.sleep(1)  # замедляем перебор
        locked_ip, locked_global = await security.register_failure(db, ip)
        if locked_ip or locked_global:
            scope = "глобально (подбор с разных IP)" if locked_global else f"для IP {ip}"
            await record(db, "security", "Вход заблокирован", f"Много неверных паролей, блокировка {scope}",
                         level="warning", ip=ip, emoji="🔐")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный пароль")

    await security.reset_failures(db, ip)
    token = await security.create_session(db, ip, request.headers.get("user-agent", ""))
    s = get_settings()
    response.set_cookie(
        security.COOKIE_NAME, token,
        max_age=s.session_ttl_days * 86400, httponly=True, secure=s.cookie_secure, samesite="strict", path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    sess = await security.get_session(db, request.cookies.get(security.COOKIE_NAME))
    if sess:
        await db.delete(sess)
        await db.commit()
    response.delete_cookie(security.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(sess=Depends(require_auth)):
    return {"ok": True, "expires_at": sess.expires_at.isoformat() + "Z"}
