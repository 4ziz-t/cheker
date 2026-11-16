from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.timeutils import utcnow


class InvestigationStatus:
    ACTIVE = "active"
    BANNED = "banned"          # все проверки показали бан → IP сменён
    NOT_BANNED = "not_banned"  # IP не в бане → «с нодой что-то не так»
    FAILED = "failed"          # проверить не удалось
    CANCELLED = "cancelled"


class Investigation(Base):
    """Проверка IP домена после падения скорости ноды: N раз с интервалом."""

    __tablename__ = "investigations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    domain_name: Mapped[str] = mapped_column(String(255))
    node_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    node_name: Mapped[str] = mapped_column(String(255), default="")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(String(16), default=InvestigationStatus.ACTIVE, index=True)
    checks_total: Mapped[int] = mapped_column(Integer, default=3)
    checks_done: Mapped[int] = mapped_column(Integer, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)   # включая неудачные
    results: Mapped[str] = mapped_column(Text, default="[]")    # JSON: [{at, blocked, error}]
    summary: Mapped[str] = mapped_column(Text, default="")

    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
