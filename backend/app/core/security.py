"""Вход по паролю из .env, сессии и защита от перебора."""
import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.timeutils import utcnow
from app.models import LoginAttempt, UserSession

COOKIE_NAME = "cheker_session"
GLOBAL_KEY = "*"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    # за Caddy реальный IP приходит в X-Forwarded-For
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), get_settings().app_password.encode())


async def _attempt(db: AsyncSession, key: str) -> LoginAttempt:
    row = await db.get(LoginAttempt, key)
    if row is None:
        row = LoginAttempt(ip=key, failures=0, window_start=utcnow())
        db.add(row)
    return row


async def lock_remaining(db: AsyncSession, ip: str) -> int:
    """Сколько секунд осталось до разблокировки (0 — не заблокирован)."""
    now = utcnow()
    remaining = 0
    for key in (ip, GLOBAL_KEY):
        row = await db.get(LoginAttempt, key)
        if row and row.locked_until and row.locked_until > now:
            remaining = max(remaining, int((row.locked_until - now).total_seconds()) + 1)
    return remaining


async def register_failure(db: AsyncSession, ip: str) -> tuple[bool, bool]:
    """Учитывает неудачу. Возвращает (ip_заблокирован, глобальная_блокировка)."""
    s = get_settings()
    now = utcnow()
    locked_ip = locked_global = False

    row = await _attempt(db, ip)
    if now - row.window_start > timedelta(minutes=s.login_window_minutes):
        row.failures, row.window_start = 0, now
    row.failures += 1
    if row.failures >= s.login_max_attempts:
        row.locked_until = now + timedelta(minutes=s.login_lock_minutes)
        row.failures, row.window_start = 0, now
        locked_ip = True

    g = await _attempt(db, GLOBAL_KEY)
    if now - g.window_start > timedelta(hours=1):
        g.failures, g.window_start = 0, now
    g.failures += 1
    if g.failures >= s.login_global_max_failures:
        g.locked_until = now + timedelta(minutes=s.login_global_lock_minutes)
        g.failures, g.window_start = 0, now
        locked_global = True

    await db.commit()
    return locked_ip, locked_global


async def reset_failures(db: AsyncSession, ip: str) -> None:
    row = await db.get(LoginAttempt, ip)
    if row:
        await db.delete(row)
        await db.commit()


async def create_session(db: AsyncSession, ip: str, user_agent: str) -> str:
    token = secrets.token_urlsafe(32)
    db.add(UserSession(
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(days=get_settings().session_ttl_days),
        ip=ip, user_agent=user_agent[:500],
    ))
    await db.commit()
    return token


async def get_session(db: AsyncSession, token: str | None) -> UserSession | None:
    if not token:
        return None
    sess = await db.get(UserSession, hash_token(token))
    if sess is None or sess.expires_at < utcnow():
        return None
    return sess
