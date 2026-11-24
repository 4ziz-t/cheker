from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.timeutils import utcnow


class DomainStatus:
    UNKNOWN = "unknown"      # ещё не проверялся
    OK = "ok"                # текущий IP чист
    BLOCKED = "blocked"      # текущий IP в бане, автосмена выключена
    NO_IPS = "no_ips"        # текущий IP в бане, свободных IP нет
    ERROR = "error"          # ошибка проверки / DNS
    NO_RECORD = "no_record"  # нет A-записи и нечего назначить


class DomainKind:
    DOMAIN = "domain"  # домен в Cloudflare, A-запись можно менять
    IP = "ip"          # голый IP (например, адрес ноды) — только мониторинг


class DomainSource:
    MANUAL = "manual"
    REMNAWAVE = "remnawave"


class Domain(Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default=DomainKind.DOMAIN, server_default=DomainKind.DOMAIN)
    source: Mapped[str] = mapped_column(String(16), default=DomainSource.MANUAL, server_default=DomainSource.MANUAL)
    # порт для проверки IP; None — глобальная настройка
    check_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_switch: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")

    current_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=DomainStatus.UNKNOWN)
    status_message: Mapped[str] = mapped_column(Text, default="")

    cf_zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cf_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    no_ips_alerted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_switch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    ips: Mapped[list["DomainIP"]] = relationship(
        back_populates="domain",
        cascade="all, delete-orphan",
        order_by="DomainIP.position",
        lazy="selectin",
    )


class DomainIP(Base):
    __tablename__ = "domain_ips"
    __table_args__ = (UniqueConstraint("domain_id", "ip", name="uq_domain_ip"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("domains.id", ondelete="CASCADE"), index=True)
    ip: Mapped[str] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(Integer, default=0)

    # None — ещё не проверялся / результат неизвестен
    is_blocked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    blocked_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON с ответами чекеров

    domain: Mapped[Domain] = relationship(back_populates="ips")
