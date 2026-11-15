"""Источник: Latency Lab — проверка бана ТСПУ.

Основной метод — POST /api/lab/tspu. Если API-ключу он не разрешён (HTTP 403 «вне scope»),
источник автоматически переходит на POST /api/lab/multiscan с tcp_port: TCP до IP:порт через
мобильных операторов РФ (МТС, Мегафон, Билайн, T2…). Режим можно зафиксировать в настройках.

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


class LatencyLabForbidden(LatencyLabError):
    pass


OPERATOR_TITLES = {"mts": "МТС", "megafon": "Мегафон", "beeline": "Билайн", "t2": "T2", "tmobile": "Т-Мобайл"}

# если /tspu запрещён для ключа — не долбим его каждый раз, а перепроверяем раз в 6 часов
TSPU_RETRY_AFTER = 6 * 3600
_tspu_forbidden_until = 0.0


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
        if resp.status_code == 403:
            raise LatencyLabForbidden(f"HTTP 403: {data.get('error') or 'нет доступа'}")
        if resp.status_code != 200 or data.get("ok") is False:
            raise LatencyLabError(f"HTTP {resp.status_code}: {data.get('error') or 'ошибка'}")
        return data

    async def _start(self, path: str, payload: dict[str, Any], deadline: float) -> dict[str, Any]:
        """Старт задачи; если у аккаунта уже идёт задача — ждём."""
        while True:
            try:
                return await self._request("POST", path, json=payload)
            except LatencyLabBusy:
                if time.monotonic() > deadline:
                    raise LatencyLabError("Аккаунт занят другой задачей слишком долго") from None
                await asyncio.sleep(5)

    async def _wait(self, data: dict[str, Any], deadline: float) -> dict[str, Any]:
        """Если сервер ответил pending — опрашиваем задачу до done."""
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
    async def _run_tspu(self, ip: str, port: int) -> dict[str, Any]:
        deadline = time.monotonic() + JOB_TIMEOUT
        payload: dict[str, Any] = {"target": ip}
        if port != 443:
            payload["port"] = port
        try:
            data = await self._start("/api/lab/tspu", payload, deadline)
        except LatencyLabForbidden:
            raise
        except LatencyLabError as e:
            # вдруг API не принимает port — повторяем без него
            if "port" in payload and "HTTP 400" in str(e):
                data = await self._start("/api/lab/tspu", {"target": ip}, deadline)
            else:
                raise
        data = await self._wait(data, deadline)
        outer = data.get("result") or {}
        # результат лежит в result.result; на всякий случай поддерживаем и плоский вариант
        inner = outer.get("result") if isinstance(outer.get("result"), dict) else outer
        inner.setdefault("_source", outer.get("source"))
        inner.setdefault("_port", outer.get("port"))
        return inner

    def _tspu_result(self, r: dict[str, Any], port: int) -> CheckResult:
        throttle_is_ban = bool(self.options.get("latencylab_throttle_is_ban", True))
        details: dict[str, Any] = {
            "mode": "tspu",
            "port": r.get("_port") or port,
            "verdict": r.get("verdict"),
            "label": r.get("label"),
            "note": r.get("note"),
            "source": r.get("_source") or r.get("operator"),
            "throttled": r.get("throttled"),
        }
        blocked, working = r.get("blocked"), r.get("working")
        if blocked is True or (throttle_is_ban and r.get("throttled") is True):
            return CheckResult(self.name, True, details=details)
        if blocked is False and working is not False:
            return CheckResult(self.name, False, details=details)
        if working is False:
            return CheckResult(self.name, None, details=details,
                               error=f"IP не отвечает: {r.get('label') or r.get('verdict') or 'сервер недоступен'}")
        return CheckResult(self.name, None, details=details, error="Latency Lab не вернул вердикт")

    # ------------------------------------------------------------ /multiscan (запасной режим)
    async def _run_multiscan(self, ip: str, port: int) -> CheckResult:
        deadline = time.monotonic() + JOB_TIMEOUT
        ops = (await self._request("GET", "/api/lab/operators")).get("result") or {}
        rows = ops.get("operators") or []
        # операторы в режиме белых списков дают ложные «баны» — пропускаем
        ids = [o["id"] for o in rows if o.get("online") and not o.get("wl")]
        if not ids:
            return CheckResult(self.name, None, error="Нет онлайн-операторов (без белых списков)")
        data = await self._start(
            "/api/lab/multiscan", {"text": ip, "tcp_port": port, "operators": ids, "async": True}, deadline
        )
        result = (await self._wait(data, deadline)).get("result") or {}

        ok_ops, fail_ops = [], []
        for row in result.get("results") or []:
            state = row.get("tcp_ok") if isinstance(row.get("tcp_ok"), bool) else row.get("ok")
            if not isinstance(state, bool):
                continue
            label = OPERATOR_TITLES.get(row.get("operator"), row.get("operator", "?"))
            (ok_ops if state else fail_ops).append(label)

        total = len(ok_ops) + len(fail_ops)
        wire_ok = result.get("wire_ok")
        details = {"mode": "multiscan", "port": port, "operators_ok": ok_ops,
                   "operators_fail": fail_ops, "wire_ok": wire_ok}
        if total == 0:
            return CheckResult(self.name, None, error="Операторы не вернули результат", details=details)
        fail_ratio = float(self.options.get("latencylab_fail_percent", 50)) / 100
        if len(fail_ops) / total >= fail_ratio:
            if wire_ok is False and not ok_ops:
                return CheckResult(self.name, None, details=details,
                                   error=f"Порт {port} недоступен и по проводу — похоже, сервер лежит")
            return CheckResult(self.name, True, details=details)
        return CheckResult(self.name, False, details=details)

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        global _tspu_forbidden_until
        if not integrations.get("latencylab_token"):
            return CheckResult(self.name, None, error="Не задан API-ключ Latency Lab (Настройки → Интеграции)")

        port = int(port or self.options.get("tcp_check_port") or 443)
        mode = self.options.get("latencylab_mode", "auto")
        use_tspu = mode == "tspu" or (mode == "auto" and time.monotonic() >= _tspu_forbidden_until)

        async with _lock:
            try:
                if use_tspu:
                    try:
                        return self._tspu_result(await self._run_tspu(ip, port), port)
                    except LatencyLabForbidden as e:
                        if mode == "tspu":
                            return CheckResult(self.name, None,
                                               error=f"Метод /tspu недоступен для API-ключа: {e}")
                        _tspu_forbidden_until = time.monotonic() + TSPU_RETRY_AFTER
                return await self._run_multiscan(ip, port)
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
            text += ". Метод /tspu не разрешён для ключа — работает запасной режим (TCP через операторов)"
        return text
