"""Источник: Latency Lab — проверка бана ТСПУ (POST /api/lab/tspu).

Запрос: {"target": "1.2.3.4"} (+ "port", если он не 443).
Ответ: result.result = {blocked, throttled, working, verdict, label, reach, ...}.
Проверка идёт «с провода» в РФ: шлётся >16 КБ вверх и смотрится, не рвёт ли ТСПУ соединение.

Нужен personal API key (ll_…) из профиля latencylab.ru. 1 IP = 1 запрос из суточного лимита.
Одновременно у аккаунта может быть только одна задача — запросы идут строго по очереди.
"""
import asyncio
import time
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core import integrations
from app.core.config import get_settings

POLL_INTERVAL = 3.0
JOB_TIMEOUT = 180.0

# у аккаунта одна активная задача — сериализуем все обращения
_lock = asyncio.Lock()


class LatencyLabError(Exception):
    pass


class LatencyLabBusy(LatencyLabError):
    pass


@register_checker
class LatencyLabChecker(BaseChecker):
    name = "latencylab"
    title = "Latency Lab · бан ТСПУ"
    description = (
        "Основной источник: проверка бана ТСПУ «с провода» в РФ (обрыв после 16 КБ, замедление). "
        "Нужен API-ключ Latency Lab, 1 IP = 1 запрос из суточного лимита"
    )
    enabled_by_default = True

    @property
    def _base(self) -> str:
        return get_settings().latencylab_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {integrations.get('latencylab_token')}"}

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            resp = await self.client.request(
                method, f"{self._base}{path}", headers=self._headers(), timeout=60, **kwargs
            )
        except httpx.HTTPError as e:
            raise LatencyLabError(f"Сетевая ошибка: {e.__class__.__name__}: {e}") from e
        try:
            data = resp.json()
        except ValueError as e:
            raise LatencyLabError(f"HTTP {resp.status_code}: ответ не JSON") from e
        if resp.status_code == 409:
            raise LatencyLabBusy(data.get("error") or "Уже есть активная задача")
        if resp.status_code != 200 or data.get("ok") is False:
            raise LatencyLabError(f"HTTP {resp.status_code}: {data.get('error') or 'ошибка'}")
        return data

    async def _start(self, payload: dict[str, Any], deadline: float) -> dict[str, Any]:
        """POST /tspu; если у аккаунта уже идёт задача — ждём."""
        while True:
            try:
                return await self._request("POST", "/api/lab/tspu", json=payload)
            except LatencyLabBusy:
                if time.monotonic() > deadline:
                    raise LatencyLabError("Аккаунт занят другой задачей слишком долго") from None
                await asyncio.sleep(5)

    async def _run_tspu(self, ip: str, port: int) -> dict[str, Any]:
        deadline = time.monotonic() + JOB_TIMEOUT
        payload: dict[str, Any] = {"target": ip}
        if port != 443:
            payload["port"] = port
        try:
            data = await self._start(payload, deadline)
        except LatencyLabError as e:
            # вдруг API не принимает port — повторяем без него
            if "port" in payload and "HTTP 400" in str(e):
                data = await self._start({"target": ip}, deadline)
            else:
                raise

        if data.get("status") == "pending":  # асинхронный режим — опрашиваем задачу
            req_id = data.get("req_id")
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                job = await self._request("GET", f"/api/lab/job/{req_id}")
                if job.get("status") == "done":
                    data = job
                    break
                if job.get("status") in ("cancelled", "error"):
                    raise LatencyLabError(job.get("error") or f"Задача {job.get('status')}")
            else:
                raise LatencyLabError("Результат не получен вовремя")

        outer = data.get("result") or {}
        # результат лежит в result.result; на всякий случай поддерживаем и плоский вариант
        inner = outer.get("result") if isinstance(outer.get("result"), dict) else outer
        inner.setdefault("_source", outer.get("source"))
        inner.setdefault("_port", outer.get("port"))
        return inner

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        if not integrations.get("latencylab_token"):
            return CheckResult(self.name, None, error="Не задан API-ключ Latency Lab (Настройки → Интеграции)")

        port = int(port or self.options.get("tcp_check_port") or 443)
        throttle_is_ban = bool(self.options.get("latencylab_throttle_is_ban", True))

        async with _lock:
            try:
                r = await self._run_tspu(ip, port)
            except LatencyLabError as e:
                return CheckResult(self.name, None, error=str(e))

        details: dict[str, Any] = {
            "port": r.get("_port") or port,
            "verdict": r.get("verdict"),
            "label": r.get("label"),
            "note": r.get("note"),
            "source": r.get("_source") or r.get("operator"),
            "throttled": r.get("throttled"),
            "reach": (r.get("reach") or {}).get("tcp"),
        }
        blocked = r.get("blocked")
        throttled = r.get("throttled") is True
        working = r.get("working")

        if blocked is True or (throttle_is_ban and throttled):
            return CheckResult(self.name, True, details=details)
        if blocked is False and working is not False:
            return CheckResult(self.name, False, details=details)
        if working is False:
            return CheckResult(self.name, None, details=details,
                               error=f"IP не отвечает: {r.get('label') or r.get('verdict') or 'сервер недоступен'}")
        return CheckResult(self.name, None, details=details, error="Latency Lab не вернул вердикт")

    async def status(self) -> str | None:
        if not integrations.get("latencylab_token"):
            return "Ключ не задан (Настройки → Интеграции)"
        try:
            stats = (await self._request("GET", "/api/lab/account/stats")).get("result") or {}
        except LatencyLabError as e:
            return f"Ошибка: {e}"
        window = stats.get("window") or {}
        return f"Запросов за сутки: {window.get('used', '?')}/{window.get('limit', '?')}"
