"""Источник: GeoPinger.net — TCP-подключение к IP:порт с узлов в сетях провайдеров РФ.

API: POST /start/tcp → task_id → GET /results/{task_id} (пока status != done).
Нужен API-токен (Профиль → API). Автоматические проверки платные: ~0.02 ₽ за точку.

Логика: если не удалось подключиться с заданной доли узлов в РФ — IP считается
заблокированным. Если заданы «контрольные» города (вне РФ) и оттуда тоже не
подключается — значит, сервер просто не отвечает, бан не фиксируем.
"""
import asyncio
import time
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core import integrations
from app.core.config import get_settings

DEFAULT_PLACES = ["Москва", "Санкт-Петербург", "Екатеринбург", "Новосибирск", "Казань"]
POLL_INTERVAL = 2.5
POLL_TIMEOUT = 90.0


class GeoPingerError(Exception):
    pass


def _ok(obj: Any) -> bool | None:
    """Пытается понять, удалось ли подключение, по ответу одного сенсора."""
    if obj is None:
        return False
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return True  # время соединения → порт открыт
    if isinstance(obj, list):
        vals = [v for v in (_ok(x) for x in obj) if v is not None]
        return any(vals) if vals else None
    if not isinstance(obj, dict):
        return None

    for nested_key in ("ports", "results", "tcp"):
        nested = obj.get(nested_key)
        if isinstance(nested, (dict, list)) and nested:
            values = nested.values() if isinstance(nested, dict) else nested
            vals = [v for v in (_ok(x) for x in values) if v is not None]
            if vals:
                return any(vals)

    for key in ("success", "ok", "open", "connected", "reachable"):
        if isinstance(obj.get(key), bool):
            return obj[key]
    if obj.get("timed_out") or obj.get("error"):
        return False
    for key in ("rtt_ms", "time", "tcp_connect", "connect_ms"):
        if isinstance(obj.get(key), (int, float)):
            return True
    return None


@register_checker
class GeoPingerTCPChecker(BaseChecker):
    name = "geopinger_tcp"
    title = "GeoPinger · TCP из РФ"
    description = "TCP-подключение к IP:порт с узлов российских провайдеров. Нужен API-токен GeoPinger (~0.02 ₽ за точку)"
    enabled_by_default = False

    @property
    def _base(self) -> str:
        return get_settings().geopinger_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {integrations.get('geopinger_token')}"}

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            resp = await self.client.request(method, f"{self._base}{path}", headers=self._headers(), **kwargs)
        except httpx.HTTPError as e:
            raise GeoPingerError(f"Сетевая ошибка: {e.__class__.__name__}: {e}") from e
        try:
            data = resp.json()
        except ValueError as e:
            raise GeoPingerError(f"HTTP {resp.status_code}: ответ не JSON") from e
        if resp.status_code != 200 or (isinstance(data, dict) and data.get("success") is False):
            err = data.get("error") if isinstance(data, dict) else None
            raise GeoPingerError(f"HTTP {resp.status_code}: {err or 'ошибка запроса'}")
        return data

    async def sensors(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/sensors")
        return data if isinstance(data, list) else []

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        if not integrations.get("geopinger_token"):
            return CheckResult(self.name, None, error="Не задан API-токен GeoPinger (Настройки → Интеграции)")

        port = int(port or self.options.get("tcp_check_port") or 443)
        places = list(self.options.get("geopinger_places") or DEFAULT_PLACES)
        control = list(self.options.get("geopinger_control_places") or [])
        fail_ratio = float(self.options.get("geopinger_fail_percent", 50)) / 100

        try:
            started = await self._request(
                "POST", "/start/tcp",
                json={"url": f"http://{ip}", "places": places + [c for c in control if c not in places],
                      "port": [port]},
            )
            task_id = started.get("task_id")
            if not task_id:
                raise GeoPingerError("Не получен task_id")

            deadline = time.monotonic() + POLL_TIMEOUT
            task: dict[str, Any] = {}
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                task = (await self._request("GET", f"/results/{task_id}")).get("task") or {}
                if task.get("status") == "done":
                    break
            results = task.get("results") or []
        except GeoPingerError as e:
            return CheckResult(self.name, None, error=str(e))

        control_set = set(control)
        ru_ok, ru_fail, ctl_ok, ctl_total = [], [], 0, 0
        for r in results:
            sensor = r.get("sensor") or {}
            city = sensor.get("city") or sensor.get("id") or "?"
            label = f"{city} ({sensor['provider']})" if sensor.get("provider") else city
            ok = _ok(r)
            if ok is None:
                continue
            is_control = city in control_set or (sensor.get("ccode") or "ru").lower() != "ru"
            if is_control:
                ctl_total += 1
                ctl_ok += int(ok)
            else:
                (ru_ok if ok else ru_fail).append(label)

        ru_total = len(ru_ok) + len(ru_fail)
        details = {
            "port": port,
            "ru": f"{len(ru_ok)}/{ru_total}",
            "failed_places": ru_fail,
            "task_id": task_id,
        }
        if ctl_total:
            details["control"] = f"{ctl_ok}/{ctl_total}"

        if ru_total == 0:
            return CheckResult(self.name, None, error="Нет ответов от узлов в РФ", details=details)
        if len(ru_fail) / ru_total >= fail_ratio:
            if ctl_total and ctl_ok == 0:
                return CheckResult(self.name, None, details=details,
                                   error=f"Порт {port} не отвечает и из-за рубежа — похоже, сервер недоступен")
            return CheckResult(self.name, True, details=details)
        return CheckResult(self.name, False, details=details)

    async def status(self) -> str | None:
        if not integrations.get("geopinger_token"):
            return "Токен не задан (Настройки → Интеграции)"
        try:
            sensors = await self.sensors()
        except GeoPingerError as e:
            return f"Ошибка: {e}"
        active = [s for s in sensors if s.get("active")]
        ru = [s for s in active if (s.get("ccode") or "").lower() == "ru"]
        return f"Активных сенсоров: {len(active)}, из них в РФ: {len(ru)}"
