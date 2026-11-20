from sqlalchemy import Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SpeedSample(Base):
    """Точка истории скорости ноды: накопленный счётчик байт на момент опроса.

    Нужна, чтобы «норма» скорости переживала перезапуск контейнера.
    """

    __tablename__ = "speed_samples"
    __table_args__ = (Index("ix_speed_samples_node_ts", "node_uuid", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    node_uuid: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[float] = mapped_column(Float, index=True)       # unix-время
    cum: Mapped[float] = mapped_column(Float)                  # накопленные байты
    mode: Mapped[str] = mapped_column(String(16))              # counter | speed
