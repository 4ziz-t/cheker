"""Отслеживание скорости нод и обнаружение её падения.

Скорость берётся из Remnawave одним из двух способов:
  • realtime-статистика панели (байт/с) — если панель её отдаёт;
  • прирост счётчика trafficUsedBytes между опросами — запасной вариант для любой версии.

Обе величины сводятся к «накопленному счётчику байт», поэтому:
  текущая скорость = прирост байт за последние N минут / N минут,
  норма           = прирост байт за предыдущие M часов / M часов.
История хранится в памяти и дублируется в SQLite (таблица speed_samples),
поэтому после перезапуска контейнера норма не набирается заново.
"""
import time
from collections import deque
from dataclasses import dataclass

MAX_HISTORY_SEC = 49 * 3600
MIN_BASELINE_COVERAGE_SEC = 30 * 60


@dataclass
class SpeedInfo:
    current_bps: float | None
    baseline_bps: float | None
    now_bps: float | None = None   # между двумя последними опросами


class SpeedTracker:
    def __init__(self) -> None:
        # uuid → deque[(ts, накопленные байты)]
        self._series: dict[str, deque[tuple[float, float]]] = {}
        self._mode: dict[str, str] = {}  # counter | speed — при смене источника историю сбрасываем
        self.realtime_supported: bool | None = None
        self.realtime_checked_at = 0.0
        # изменения, ещё не записанные в базу (см. flush)
        self._pending_add: list[tuple[str, float, float, str]] = []
        self._pending_clear: set[str] = set()
        self._last_prune = 0.0

    # ---------- база ----------

    async def load(self, db) -> int:
        """Восстанавливает историю из базы при старте. Возвращает число точек."""
        from sqlalchemy import delete, select

        from app.models import SpeedSample

        cutoff = time.time() - MAX_HISTORY_SEC
        await db.execute(delete(SpeedSample).where(SpeedSample.ts < cutoff))
        await db.commit()
        rows = (await db.execute(
            select(SpeedSample.node_uuid, SpeedSample.ts, SpeedSample.cum, SpeedSample.mode)
            .order_by(SpeedSample.node_uuid, SpeedSample.ts)
        )).all()
        self._series.clear()
        self._mode.clear()
        for uuid, ts, cum, mode in rows:
            if self._mode.get(uuid) != mode:  # источник менялся — берём только последний отрезок
                self._mode[uuid] = mode
                self._series[uuid] = deque()
            series = self._series[uuid]
            if series and mode == "counter" and cum < series[-1][1]:
                series.clear()
            series.append((ts, cum))
        self._pending_add.clear()
        self._pending_clear.clear()
        return len(rows)

    async def flush(self, db) -> None:
        """Записывает накопленные изменения в базу (коммит — на вызывающем)."""
        from sqlalchemy import delete

        from app.models import SpeedSample

        if self._pending_clear:
            await db.execute(delete(SpeedSample).where(SpeedSample.node_uuid.in_(list(self._pending_clear))))
            self._pending_clear.clear()
        if self._pending_add:
            db.add_all([SpeedSample(node_uuid=u, ts=t, cum=c, mode=m) for u, t, c, m in self._pending_add])
            self._pending_add.clear()
        now = time.time()
        if now - self._last_prune > 600:
            self._last_prune = now
            await db.execute(delete(SpeedSample).where(SpeedSample.ts < now - MAX_HISTORY_SEC))

    def _clear(self, uuid: str) -> None:
        self._series.pop(uuid, None)
        self._pending_clear.add(uuid)
        self._pending_add = [p for p in self._pending_add if p[0] != uuid]

    def _push(self, uuid: str, ts: float, cum: float) -> None:
        series = self._series.setdefault(uuid, deque())
        series.append((ts, cum))
        self._pending_add.append((uuid, ts, cum, self._mode.get(uuid, "counter")))
        while series and ts - series[0][0] > MAX_HISTORY_SEC:
            series.popleft()

    def add_counter(self, uuid: str, total_bytes: int, ts: float | None = None) -> None:
        """Накопленный счётчик трафика ноды (trafficUsedBytes)."""
        ts = ts or time.time()
        self._set_mode(uuid, "counter")
        series = self._series.get(uuid)
        if series and total_bytes < series[-1][1]:
            self._clear(uuid)  # счётчик сбросили (например, новый месяц)
        self._push(uuid, ts, float(total_bytes))

    def bytes_in(self, uuid: str, seconds: float, ts: float | None = None) -> tuple[float, float] | None:
        """Сколько байт прошло через ноду за последние seconds секунд.

        Возвращает (байты, сколько секунд реально покрыто историей) или None, если истории нет.
        """
        series = self._series.get(uuid)
        if not series or len(series) < 2:
            return None
        end_ts, end_cum = series[-1]
        start = end_ts - seconds
        # последняя точка не позже начала окна (или самая первая, если истории меньше окна)
        start_ts, start_cum = series[0]
        for t, c in series:
            if t <= start:
                start_ts, start_cum = t, c
            else:
                break
        return max(end_cum - start_cum, 0.0), end_ts - start_ts

    def add_speed(self, uuid: str, bps: float, ts: float | None = None) -> None:
        """Мгновенная скорость (байт/с) — переводим в накопленный счётчик."""
        ts = ts or time.time()
        self._set_mode(uuid, "speed")
        series = self._series.get(uuid)
        if not series:
            self._push(uuid, ts, 0.0)
            return
        last_ts, last_cum = series[-1]
        dt = max(ts - last_ts, 0)
        self._push(uuid, ts, last_cum + bps * dt)

    def _set_mode(self, uuid: str, mode: str) -> None:
        if self._mode.get(uuid) != mode:
            had_mode = uuid in self._mode
            self._mode[uuid] = mode
            if had_mode or uuid in self._series:
                self._clear(uuid)

    def forget(self, uuid: str) -> None:
        if uuid in self._series or uuid in self._mode:
            self._clear(uuid)
        self._mode.pop(uuid, None)

    @staticmethod
    def _at(series: deque[tuple[float, float]], t: float) -> tuple[float, float] | None:
        """Последняя точка не позже момента t."""
        found = None
        for point in series:
            if point[0] <= t:
                found = point
            else:
                break
        return found

    def info(self, uuid: str, window_min: int, baseline_hours: int, now: float | None = None) -> SpeedInfo:
        now = now or time.time()
        series = self._series.get(uuid)
        if not series or len(series) < 2:
            return SpeedInfo(None, None)
        end = series[-1]
        prev = series[-2]
        now_bps = (end[1] - prev[1]) / (end[0] - prev[0]) if end[0] > prev[0] else None
        window_start = self._at(series, now - window_min * 60)
        current = None
        if window_start and end[0] - window_start[0] >= window_min * 60 * 0.8:
            current = (end[1] - window_start[1]) / (end[0] - window_start[0])

        baseline = None
        if window_start:
            base_start = self._at(series, window_start[0] - baseline_hours * 3600) or series[0]
            span = window_start[0] - base_start[0]
            if span >= min(MIN_BASELINE_COVERAGE_SEC, baseline_hours * 3600):
                baseline = (window_start[1] - base_start[1]) / span
        return SpeedInfo(current, baseline, now_bps)


tracker = SpeedTracker()


def mbps(bps: float | None) -> str:
    """байт/с → «12.3 Мбит/с»."""
    if bps is None:
        return "—"
    return f"{bps * 8 / 1_000_000:.1f} Мбит/с"
