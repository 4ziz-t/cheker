"""Источник: https://cheburcheck.ru (бесплатный метод /check, без токена)."""
import asyncio

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core.config import get_settings


@register_checker
class CheburcheckChecker(BaseChecker):
    name = "cheburcheck"
    title = "Cheburcheck"
    description = "Проверка IP по реестру блокировок РКН (cheburcheck.ru, бесплатный /check)"
    enabled_by_default = True

    retries_on_429 = 2
    retry_delay = 10.0

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        url = f"{get_settings().cheburcheck_url.rstrip('/')}/check"
        attempt = 0
        while True:
            try:
                resp = await self.client.get(url, params={"target": ip})
            except httpx.HTTPError as e:
                return CheckResult(self.name, None, error=f"Сетевая ошибка: {e.__class__.__name__}: {e}")

            if resp.status_code == 429 and attempt < self.retries_on_429:
                attempt += 1
                await asyncio.sleep(self.retry_delay * attempt)
                continue
            break

        if resp.status_code != 200:
            info = ""
            try:
                info = resp.json().get("info", "")
            except ValueError:
                info = resp.text[:200]
            return CheckResult(self.name, None, error=f"HTTP {resp.status_code}: {info}".strip())

        try:
            data = resp.json()
        except ValueError:
            return CheckResult(self.name, None, error="Некорректный JSON в ответе")

        blocked = data.get("blocked")
        if not isinstance(blocked, bool):
            return CheckResult(self.name, None, error="В ответе нет поля blocked")

        details = {
            "blocked_subnets": data.get("blocked_subnets") or [],
            "geo": (data.get("geo") or {}).get("location"),
            "cdn_providers": data.get("cdn_providers") or {},
        }
        return CheckResult(self.name, blocked, details=details)
