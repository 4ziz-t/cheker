"""Отслеживание скорости нод и обнаружение её падения.

Скорость берётся из Remnawave одним из двух способов:
  • realtime-статистика панели (байт/с) — если панель её отдаёт;
  • прирост счётчика trafficUsedBytes между опросами — запасной вариант для любой версии.

Обе величины сводятся к «накопленному счётчику байт», поэтому:
  текущая скорость = прирост байт за последние N минут / N минут,
  норма           = прирост байт за предыдущие M часов / M часов.
История хранится в памяти процесса (после перезапуска норма набирается заново).
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


class SpeedTracker:
    def __init__(self) -> None:
        # uuid → deque[(ts, накопленные байты)]
        self._series: dict[str, deque[tuple[float, float]]] = {}
        self._mode: dict[str, str] = {}  # counter | speed — при смене источника историю сбрасываем
        self.realtime_supported: bool | None = None
        self.realtime_checked_at = 0.0

    def _push(self, uuid: str, ts: float, cum: float) -> None:
        series = self._series.setdefault(uuid, deque())
        series.append((ts, cum))
        while series and ts - series[0][0] > MAX_HISTORY_SEC:
            series.popleft()

    def add_counter(self, uuid: str, total_bytes: int, ts: float | None = None) -> None:
        """Накопленный счётчик трафика ноды (trafficUsedBytes)."""
        ts = ts or time.time()
        self._set_mode(uuid, "counter")
        series = self._series.get(uuid)
        if series and total_bytes < series[-1][1]:
            series.clear()  # счётчик сбросили (например, новый месяц)
        self._push(uuid, ts, float(total_bytes))

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
            self._mode[uuid] = mode
            self._series.pop(uuid, None)

    def forget(self, uuid: str) -> None:
        self._series.pop(uuid, None)
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
        return SpeedInfo(current, baseline)


tracker = SpeedTracker()


def mbps(bps: float | None) -> str:
    """байт/с → «12.3 Мбит/с»."""
    if bps is None:
        return "—"
    return f"{bps * 8 / 1_000_000:.1f} Мбит/с"
