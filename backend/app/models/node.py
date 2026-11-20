from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutils import utcnow


class Node(Base):
    """Кэш состояния нод Remnawave (источник правды — панель)."""

    __tablename__ = "nodes"

    uuid: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country_code: Mapped[str] = mapped_column(String(8), default="")

    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_connecting: Mapped[bool] = mapped_column(Boolean, default=False)
    users_online: Mapped[int | None] = mapped_column(Integer, nullable=True)
    xray_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_status_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    offline_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # уже отправлено «нода offline» и ещё не было «снова online» — повторно не шлём
    alert_offline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # скорость (байт/с): текущая (среднее за окно) и «норма» (среднее за последние часы)
    speed_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_now_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # realtime | counter
    baseline_bps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speed_drop_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
