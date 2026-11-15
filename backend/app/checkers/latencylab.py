"""Источник: Latency Lab — проверка IP через реальные мобильные модемы операторов РФ
(МТС, Мегафон, Билайн, T2, Т-Мобайл). Основной источник для обнаружения бана ТСПУ.

API: POST /api/lab/multiscan {text, tcp_port, async: true} → req_id
     GET  /api/lab/job/{req_id} до status = done.
Нужен personal API key (ll_…) из профиля latencylab.ru. 1 IP = 1 запрос из суточного лимита.
Одновременно у аккаунта может быть только одна задача — запросы идут строго по очереди.

Решение: если до IP не достучались с заданной доли операторов — бан.
Если проверка «по проводу» (wire precheck) тоже не прошла — сервер лежит, бан не фиксируем.
"""
import asyncio
import time
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core import integrations
from app.core.config import get_settings

OPERATOR_TITLES = {
    "mts": "МТС",
    "megafon": "Мегафон",
    "beeline": "Билайн",
    "t2": "T2",
    "tmobile": "Т-Мобайл",
}
POLL_INTERVAL = 3.0
JOB_TIMEOUT = 180.0

# у аккаунта одна активная задача — сериализуем все обращения
_lock = asyncio.Lock()


class LatencyLabError(Exception):
    pass


class LatencyLabBusy(LatencyLabError):
    pass


def _row_ok(row: dict[str, Any], port_mode: bool) -> bool | None:
    if port_mode and isinstance(row.get("tcp_ok"), bool):
        return row["tcp_ok"]
    if isinstance(row.get("ok"), bool):
        return row["ok"]
    if isinstance(row.get("available"), bool):
        return row["available"]
    return None


@register_checker
class LatencyLabChecker(BaseChecker):
    name = "latencylab"
    title = "Latency Lab · ТСПУ (мобильные операторы)"
    description = (
        "Основной источник: TCP до IP:порт через модемы МТС, Мегафон, Билайн, T2. "
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

    async def operators(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/lab/operators")
        return (data.get("result") or {}).get("operators") or []

    async def _run_multiscan(self, payload: dict[str, Any]) -> dict[str, Any]:
        deadline = time.monotonic() + JOB_TIMEOUT
        # старт задачи (если занято — ждём завершения чужой/прошлой задачи)
        while True:
            try:
                started = await self._request("POST", "/api/lab/multiscan", json=payload)
                break
            except LatencyLabBusy:
                if time.monotonic() > deadline:
                    raise LatencyLabError("Аккаунт занят другой задачей слишком долго") from None
                await asyncio.sleep(5)

        if started.get("status") != "pending":  # сервер ответил синхронно
            return started.get("result") or {}

        req_id = started.get("req_id")
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            job = await self._request("GET", f"/api/lab/job/{req_id}")
            status = job.get("status")
            if status == "done":
                return job.get("result") or {}
            if status in ("cancelled", "error"):
                raise LatencyLabError(job.get("error") or f"Задача {status}")
        try:
            await self._request("POST", "/api/lab/cancel", json={"req_id": req_id})
        except LatencyLabError:
            pass
        raise LatencyLabError("Результат не получен вовремя")

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        if not integrations.get("latencylab_token"):
            return CheckResult(self.name, None, error="Не задан API-ключ Latency Lab (Настройки → Интеграции)")

        port = int(port or self.options.get("tcp_check_port") or 443)
        selected = list(self.options.get("latencylab_operators") or [])
        skip_wl = bool(self.options.get("latencylab_skip_whitelist", True))
        fail_ratio = float(self.options.get("latencylab_fail_percent", 50)) / 100

        async with _lock:
            try:
                ops = await self.operators()
                online = [o for o in ops if o.get("online")]
                if skip_wl:
                    online = [o for o in online if not o.get("wl")]
                ids = [o["id"] for o in online if not selected or o.get("id") in selected]
                if not ids:
                    return CheckResult(self.name, None, error="Нет подходящих операторов онлайн")
                result = await self._run_multiscan(
                    {"text": ip, "tcp_port": port, "operators": ids, "async": True}
                )
            except LatencyLabError as e:
                return CheckResult(self.name, None, error=str(e))

        ok_ops, fail_ops = [], []
        for row in result.get("results") or []:
            state = _row_ok(row, port_mode=True)
            if state is None:
                continue
            label = OPERATOR_TITLES.get(row.get("operator"), row.get("operator", "?"))
            (ok_ops if state else fail_ops).append(label)

        total = len(ok_ops) + len(fail_ops)
        wire_ok = result.get("wire_ok")
        details: dict[str, Any] = {
            "port": port,
            "operators_ok": ok_ops,
            "operators_fail": fail_ops,
            "wire_ok": wire_ok,
        }
        if total == 0:
            return CheckResult(self.name, None, error="Операторы не вернули результат", details=details)
        if len(fail_ops) / total >= fail_ratio:
            if wire_ok is False and not ok_ops:
                return CheckResult(self.name, None, details=details,
                                   error=f"Порт {port} недоступен и по проводу — похоже, сервер лежит")
            return CheckResult(self.name, True, details=details)
        return CheckResult(self.name, False, details=details)

    async def status(self) -> str | None:
        if not integrations.get("latencylab_token"):
            return "Ключ не задан (Настройки → Интеграции)"
        try:
            stats = (await self._request("GET", "/api/lab/account/stats")).get("result") or {}
            ops = await self.operators()
        except LatencyLabError as e:
            return f"Ошибка: {e}"
        window = stats.get("window") or {}
        online = [OPERATOR_TITLES.get(o["id"], o["id"]) for o in ops if o.get("online")]
        return (f"Запросов за сутки: {window.get('used', '?')}/{window.get('limit', '?')}. "
                f"Онлайн: {', '.join(online) or 'никого'}")
