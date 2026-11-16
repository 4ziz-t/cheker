"""Источник: Latency Lab — единственный источник проверки IP.

Смотрим на результат «с провода» (wire) — проверку из проводной сети РФ:
если по проводу IP недоступен — считаем, что IP заблокирован.

Порядок:
  1. POST /api/lab/tspu {"target": ip} — если метод разрешён API-ключу.
     Источник там wire: blocked=true или working=false → бан.
     При HTTP 403 (метод вне scope ключа) переходим к п.2 и пробуем /tspu снова через 6 часов.
  2. POST /api/lab/multiscan {"text": ip, "tcp_port": port, "async": true} → поле wire_ok.
     wire_ok=false → бан, wire_ok=true → чисто.
     Если wire_ok не пришёл — запасной вариант: доля операторов, у которых порт недоступен.

Нужен personal API key (ll_…). 1 IP = 1 запрос из суточного лимита.
Одновременно у аккаунта одна задача — запросы идут строго по очереди.
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
TSPU_RETRY_AFTER = 6 * 3600

OPERATOR_TITLES = {"mts": "МТС", "megafon": "Мегафон", "beeline": "Билайн", "t2": "T2", "tmobile": "Т-Мобайл"}

_lock = asyncio.Lock()            # у аккаунта одна активная задача
_tspu_forbidden_until = 0.0       # /tspu не разрешён ключу — не дёргаем его до этого момента


class LatencyLabError(Exception):
    pass


class LatencyLabBusy(LatencyLabError):
    pass


class LatencyLabForbidden(LatencyLabError):
    pass


@register_checker
class LatencyLabChecker(BaseChecker):
    name = "latencylab"
    title = "Latency Lab"
    description = (
        "Проверка IP «с провода» в РФ: если по проводу IP недоступен — он заблокирован. "
        "1 проверка = 1 запрос из суточного лимита ключа"
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
        if resp.status_code == 403:
            raise LatencyLabForbidden(f"HTTP 403: {data.get('error') or 'нет доступа'}")
        if resp.status_code != 200 or data.get("ok") is False:
            raise LatencyLabError(f"HTTP {resp.status_code}: {data.get('error') or 'ошибка'}")
        return data

    async def _start(self, path: str, payload: dict[str, Any], deadline: float) -> dict[str, Any]:
        while True:
            try:
                return await self._request("POST", path, json=payload)
            except LatencyLabBusy:
                if time.monotonic() > deadline:
                    raise LatencyLabError("Аккаунт занят другой задачей слишком долго") from None
                await asyncio.sleep(5)

    async def _wait(self, data: dict[str, Any], deadline: float) -> dict[str, Any]:
        if data.get("status") != "pending":
            return data
        req_id = data.get("req_id")
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_INTERVAL)
            job = await self._request("GET", f"/api/lab/job/{req_id}")
            if job.get("status") == "done":
                return job
            if job.get("status") in ("cancelled", "error"):
                raise LatencyLabError(job.get("error") or f"Задача {job.get('status')}")
        try:
            await self._request("POST", "/api/lab/cancel", json={"req_id": req_id})
        except LatencyLabError:
            pass
        raise LatencyLabError("Результат не получен вовремя")

    # ------------------------------------------------------------ /tspu
    async def _via_tspu(self, ip: str, port: int) -> CheckResult:
        deadline = time.monotonic() + JOB_TIMEOUT
        payload: dict[str, Any] = {"target": ip}
        if port != 443:
            payload["port"] = port
        data = await self._wait(await self._start("/api/lab/tspu", payload, deadline), deadline)
        outer = data.get("result") or {}
        r = outer.get("result") if isinstance(outer.get("result"), dict) else outer

        bad = r.get("blocked") is True or r.get("working") is False
        details = {
            "method": "tspu",
            "port": outer.get("port") or port,
            "wire_ok": not bad,
            "verdict": r.get("verdict"),
            "label": r.get("label"),
        }
        if bad:
            return CheckResult(self.name, True, details=details)
        if r.get("blocked") is False:
            return CheckResult(self.name, False, details=details)
        return CheckResult(self.name, None, details=details, error="Latency Lab не вернул вердикт")

    # ------------------------------------------------------------ /multiscan
    async def _via_multiscan(self, ip: str, port: int) -> CheckResult:
        deadline = time.monotonic() + JOB_TIMEOUT
        data = await self._start(
            "/api/lab/multiscan", {"text": ip, "tcp_port": port, "async": True}, deadline
        )
        result = (await self._wait(data, deadline)).get("result") or {}
        wire_ok = result.get("wire_ok")

        ok_ops, fail_ops = [], []
        for row in result.get("results") or []:
            state = row.get("tcp_ok") if isinstance(row.get("tcp_ok"), bool) else row.get("ok")
            if isinstance(state, bool):
                label = OPERATOR_TITLES.get(row.get("operator"), row.get("operator", "?"))
                (ok_ops if state else fail_ops).append(label)

        details: dict[str, Any] = {
            "method": "multiscan",
            "port": port,
            "wire_ok": wire_ok,
            "operators_ok": ok_ops,
            "operators_fail": fail_ops,
        }
        if wire_ok is False:
            return CheckResult(self.name, True, details=details)
        if wire_ok is True:
            return CheckResult(self.name, False, details=details)

        # wire не пришёл — запасной вариант по операторам
        total = len(ok_ops) + len(fail_ops)
        if not total:
            return CheckResult(self.name, None, details=details, error="Нет данных wire и операторов")
        details["fallback"] = "operators"
        fail_ratio = float(self.options.get("latencylab_fail_percent", 50)) / 100
        return CheckResult(self.name, len(fail_ops) / total >= fail_ratio, details=details)

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        global _tspu_forbidden_until
        if not integrations.get("latencylab_token"):
            return CheckResult(self.name, None, error="Не задан API-ключ Latency Lab (Настройки → Интеграции)")
        port = int(port or self.options.get("tcp_check_port") or 443)

        async with _lock:
            try:
                if time.monotonic() >= _tspu_forbidden_until:
                    try:
                        return await self._via_tspu(ip, port)
                    except LatencyLabForbidden:
                        _tspu_forbidden_until = time.monotonic() + TSPU_RETRY_AFTER
                return await self._via_multiscan(ip, port)
            except LatencyLabError as e:
                return CheckResult(self.name, None, error=str(e))

    async def status(self) -> str | None:
        if not integrations.get("latencylab_token"):
            return "Ключ не задан (Настройки → Интеграции)"
        try:
            stats = (await self._request("GET", "/api/lab/account/stats")).get("result") or {}
        except LatencyLabError as e:
            return f"Ошибка: {e}"
        window = stats.get("window") or {}
        text = f"Запросов за сутки: {window.get('used', '?')}/{window.get('limit', '?')}"
        if time.monotonic() < _tspu_forbidden_until:
            text += ". Метод /tspu не разрешён ключу — используется /multiscan (wire)"
        return text
