from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def utcnow() -> datetime:
    """Текущее время в UTC без tzinfo (так хранится в SQLite)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().tz)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(local_tz())


def fmt_local(dt: datetime | None) -> str:
    loc = to_local(dt)
    return loc.strftime("%d.%m.%Y %H:%M") if loc else "—"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d:
        parts.append(f"{d} д")
    if h:
        parts.append(f"{h} ч")
    if m or not parts:
        parts.append(f"{m} мин")
    return " ".join(parts)
