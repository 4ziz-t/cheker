"""Источник: динамическая проверка cheburcheck (пробы из сетей РФ, ловят ТСПУ).

Нужен API-токен (CHEBURCHECK_TOKEN). Каждая проверка расходует кредиты,
но повторная проверка того же IP в течение ~3 часов берётся из кэша cheburcheck.

Схема: GET /check?target=IP → id → GET /probe/{id} (SSE: started → result… → done).
"""
import asyncio
import json
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core import integrations
from app.core.config import get_settings

# вердикты проб, которые считаем блокировкой
BLOCK_VERDICTS = {"tspu_block", "sni_block", "cdn_block", "dns_spoofing"}

VERDICT_TITLES = {
    "ok": "доступен",
    "uncertain": "неопределённо",
    "tspu_block": "ТСПУ",
    "sni_block": "SNI-блок",
    "cdn_block": "CDN-блок",
    "dns_spoofing": "подмена DNS",
    "whitelist": "белый список",
}


class ProbeError(Exception):
    pass


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        return f"HTTP {resp.status_code}: {data.get('info') or data.get('code') or ''}".strip()
    except ValueError:
        return f"HTTP {resp.status_code}"


@register_checker
class CheburcheckProbeChecker(BaseChecker):
    name = "cheburcheck_probe"
    title = "Cheburcheck · ТСПУ (пробы)"
    description = "Динамическая проверка с узлов в РФ — ловит блокировки ТСПУ. Нужен API-токен Cheburcheck, расходует кредиты"
    enabled_by_default = False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {integrations.get('cheburcheck_token')}"}

    @property
    def _base(self) -> str:
        return get_settings().cheburcheck_url.rstrip("/")

    async def _get_context_id(self, ip: str) -> str:
        for attempt in range(3):
            resp = await self.client.get(f"{self._base}/check", params={"target": ip})
            if resp.status_code == 429 and attempt < 2:
                await asyncio.sleep(10 * (attempt + 1))
                continue
            if resp.status_code != 200:
                raise ProbeError(f"/check {_error_text(resp)}")
            ctx = resp.json().get("id")
            if not ctx:
                raise ProbeError("/check не вернул id")
            return ctx
        raise ProbeError("/check: превышен лимит запросов")

    async def _read_probe(self, ctx: str) -> list[dict[str, Any]]:
        s = get_settings()
        results: list[dict[str, Any]] = []
        timeout = httpx.Timeout(15.0, read=s.cheburcheck_probe_timeout)
        async with self.client.stream(
            "GET", f"{self._base}/probe/{ctx}", headers=self._headers(), timeout=timeout
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raise ProbeError(f"/probe {_error_text(resp)}")

            event, data_lines = None, []
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    if event and data_lines:
                        try:
                            payload = json.loads("\n".join(data_lines))
                        except ValueError:
                            payload = {}
                        if event == "result":
                            results.append(payload)
                        elif event == "done":
                            return results
                    event, data_lines = None, []
        return results

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        s = get_settings()
        if not integrations.get("cheburcheck_token"):
            return CheckResult(self.name, None, error="Не задан API-токен Cheburcheck (Настройки → Интеграции)")
        try:
            ctx = await self._get_context_id(ip)
            results = await asyncio.wait_for(self._read_probe(ctx), timeout=s.cheburcheck_probe_timeout + 30)
        except ProbeError as e:
            return CheckResult(self.name, None, error=str(e))
        except asyncio.TimeoutError:
            return CheckResult(self.name, None, error="Пробы не ответили вовремя")
        except httpx.HTTPError as e:
            return CheckResult(self.name, None, error=f"Сетевая ошибка: {e.__class__.__name__}: {e}")

        if not results:
            return CheckResult(self.name, None, error="Нет онлайн-проб, результат неизвестен")

        probes = []
        blocked_by: list[str] = []
        has_ok = False
        for r in results:
            verdicts = [v for v in (r.get("verdicts") or []) if isinstance(v, str)]
            probes.append({
                "probe": str(r.get("probe_id", "?")),
                "verdicts": [VERDICT_TITLES.get(v, v) for v in verdicts],
                "cached": bool(r.get("cached")),
            })
            hit = [v for v in verdicts if v in BLOCK_VERDICTS]
            if hit:
                blocked_by.extend(hit)
            elif "ok" in verdicts or "whitelist" in verdicts:
                has_ok = True

        details = {
            "probes": probes,
            "verdicts": sorted({VERDICT_TITLES.get(v, v) for v in blocked_by}),
        }
        if blocked_by:
            return CheckResult(self.name, True, details=details)
        if has_ok:
            return CheckResult(self.name, False, details=details)
        return CheckResult(self.name, None, error="Все пробы вернули «неопределённо»", details=details)

    async def status(self) -> str | None:
        if not integrations.get("cheburcheck_token"):
            return "Токен не задан (Настройки → Интеграции)"
        try:
            resp = await self.client.get(f"{self._base}/credits", headers=self._headers(), timeout=10)
        except httpx.HTTPError as e:
            return f"Не удалось получить баланс: {e.__class__.__name__}"
        if resp.status_code != 200:
            return f"Баланс: ошибка {_error_text(resp)}"
        return f"Кредитов: {resp.json().get('credits', '?')}"
