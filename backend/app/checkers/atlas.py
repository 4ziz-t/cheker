"""Источник: Red Atlas (atlas.redline.ac).

Живая проверка: адрес проверяют три точки Globalping в России (разные сети: МТС, Таймвеб…)
и контрольная точка в Европе. Ключ не нужен.

  POST /check {"target": ip}  → {"id": "…", "cached": bool}
  GET  /check/{id}            → status running | done | error, result:
       status        open | partial | mixed | blocked | down
       ru / ru_ok / ru_total — точки в России, ctrl / ctrl_ok — контроль из Европы
       registry.blocked      — адрес в реестре блокировок

Решение:
  • в реестре или status=blocked → бан;
  • down (не открывается нигде, в том числе из Европы) → это не бан, а неработающий сервер:
    ошибка, в проверки не засчитывается;
  • иначе бан, если из России не открывается atlas_fail_percent % точек и больше,
    а из Европы адрес открывается.

Лимит сервиса: 6 живых проверок за 10 минут с одного адреса (ответ кэшируется на 10 минут).
Проверки идут по очереди; когда лимит выбран — ждём свободного места
(не дольше atlas_max_wait_sec), при 429 учитываем Retry-After.
"""
import asyncio
import time
from collections import deque
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core.config import get_settings

LIVE_LIMIT = 6
LIVE_WINDOW = 600.0
POLL_INTERVAL = 2.0
JOB_TIMEOUT = 90.0

_lock = asyncio.Lock()
_started: deque[float] = deque()   # время запусков живых проверок (для лимита 6 / 10 мин)
_blocked_until = 0.0               # 429 от сервиса — до этого момента не шлём


class AtlasError(Exception):
    pass


class AtlasRateLimited(AtlasError):
    def __init__(self, wait: float):
        super().__init__("лимит Red Atlas")
        self.wait = wait


def _wait_for_slot() -> float:
    """Сколько секунд ждать до свободной живой проверки (0 — можно сейчас)."""
    now = time.monotonic()
    while _started and now - _started[0] >= LIVE_WINDOW:
        _started.popleft()
    wait = max(_blocked_until - now, 0.0)
    if len(_started) >= LIVE_LIMIT:
        wait = max(wait, _started[0] + LIVE_WINDOW - now)
    return wait


def _point(p: dict[str, Any]) -> dict[str, Any]:
    rtt = p.get("rtt")
    return {
        "city": p.get("city") or "",
        "net": p.get("net") or "",
        "asn": p.get("asn"),
        "ok": p.get("ok"),
        "rtt": round(rtt) if isinstance(rtt, (int, float)) else None,
    }


@register_checker
class AtlasChecker(BaseChecker):
    name = "atlas"
    title = "Red Atlas"
    description = (
        "Адрес проверяют три точки в России (разные сети) и контрольная точка "
        "в Европе, плюс сверка с реестром блокировок. Бесплатно, без ключа; лимит сервиса — "
        "6 живых проверок за 10 минут, остальные ждут в очереди"
    )
    enabled_by_default = True

    @property
    def _base(self) -> str:
        return get_settings().atlas_url.rstrip("/")

    async def _request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        global _blocked_until
        try:
            resp = await self.client.request(method, f"{self._base}{path}", timeout=30, **kwargs)
        except httpx.HTTPError as e:
            raise AtlasError(f"Сетевая ошибка: {e.__class__.__name__}: {e}") from e
        if resp.status_code == 429:
            try:
                wait = float(resp.headers.get("Retry-After") or 60)
            except ValueError:
                wait = 60.0
            _blocked_until = time.monotonic() + wait
            raise AtlasRateLimited(wait)
        try:
            data = resp.json()
        except ValueError as e:
            raise AtlasError(f"HTTP {resp.status_code}: ответ не JSON") from e
        if resp.status_code != 200:
            raise AtlasError(f"HTTP {resp.status_code}: {data.get('error') or 'ошибка'}")
        return data

    async def _live(self, ip: str, port: int) -> dict[str, Any]:
        raw = self.options.get("atlas_max_wait_sec")
        max_wait = float(600 if raw is None or raw == "" else raw)
        deadline = time.monotonic() + max_wait
        async with _lock:  # строго по одной, чтобы правильно считать лимит
            while True:
                wait = _wait_for_slot()
                if wait > 0:
                    if time.monotonic() + wait > deadline:
                        raise AtlasError(
                            f"лимит Red Atlas: 6 проверок за 10 минут, свободно через {int(wait)} с — повторите позже"
                        )
                    await asyncio.sleep(wait)
                    continue
                try:
                    payload: dict[str, Any] = {"target": ip}
                    if port and port != 443:
                        payload["port"] = port
                    started = await self._request("POST", "/check", json=payload)
                except AtlasRateLimited:
                    continue  # подождём Retry-After в начале цикла
                if not started.get("cached"):
                    _started.append(time.monotonic())
                break

        job_id = started.get("id")
        if not job_id:
            raise AtlasError("сервис не вернул номер проверки")
        end = time.monotonic() + JOB_TIMEOUT
        while True:
            job = await self._request("GET", f"/check/{job_id}")
            if job.get("status") == "done":
                result = job.get("result") or {}
                result["_cached"] = bool(started.get("cached"))
                return result
            if job.get("status") == "error":
                raise AtlasError(job.get("error") or "проверка завершилась с ошибкой")
            if time.monotonic() > end:
                raise AtlasError("результат не получен вовремя")
            await asyncio.sleep(POLL_INTERVAL)

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        port = port or 443
        try:
            r = await self._live(ip, port)
        except AtlasError as e:
            return CheckResult(self.name, None, error=str(e))

        ru = [_point(p) for p in r.get("ru") or []]
        ctrl = [_point(p) for p in r.get("ctrl") or []]
        ru_total = int(r.get("ru_total") or len(ru))
        ru_ok = int(r.get("ru_ok") if r.get("ru_ok") is not None else sum(1 for p in ru if p["ok"]))
        ctrl_ok = r.get("ctrl_ok")
        registry = r.get("registry") or {}
        status = r.get("status") or ""

        details: dict[str, Any] = {
            "status": status,
            "status_text": r.get("status_text") or "",
            "reason_text": r.get("reason_text") or "",
            "proto": r.get("proto"),
            "port": r.get("port") or port,
            "ru_ok": ru_ok,
            "ru_total": ru_total,
            "ru": ru,
            "ctrl_ok": ctrl_ok,
            "ctrl_total": r.get("ctrl_total") or len(ctrl),
            "ctrl": ctrl,
            "registry_blocked": registry.get("blocked"),
            "whitelist": registry.get("whitelist"),
            "checked_at": r.get("ts"),
            "cached": r.get("_cached", False),
        }

        if registry.get("blocked") is True:
            details["verdict"] = "в реестре блокировок"
            return CheckResult(self.name, True, details=details)
        if status == "blocked":
            details["verdict"] = "заблокирован в России"
            return CheckResult(self.name, True, details=details)
        if status == "down":
            return CheckResult(
                self.name, None, details=details,
                error="адрес не отвечает ни из России, ни из Европы — похоже, не работает сам сервер",
            )
        if not ru_total:
            return CheckResult(self.name, None, details=details, error="нет ответов от точек в России")

        fail_pct = (ru_total - ru_ok) * 100 / ru_total
        threshold = float(self.options.get("atlas_fail_percent") or 50)
        europe_ok = ctrl_ok is None or (isinstance(ctrl_ok, (int, float)) and ctrl_ok != 0)
        blocked = fail_pct >= threshold and europe_ok
        if fail_pct >= threshold and not europe_ok:
            return CheckResult(
                self.name, None, details=details,
                error="из России и из Европы не открывается — похоже, проблема на самом сервере",
            )
        details["verdict"] = "не открывается из России" if blocked else "открывается из России"
        return CheckResult(self.name, blocked, details=details)

    async def status(self) -> str | None:
        wait = _wait_for_slot()
        used = len(_started)
        if wait > 0:
            return f"лимит живых проверок выбран, свободно через {int(wait)} с"
        return f"без ключа · живых проверок за 10 мин: {used} из {LIVE_LIMIT}"
