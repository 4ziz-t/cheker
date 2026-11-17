"""Работа с DNS Cloudflare.

Поддерживаются оба вида API-токенов:
  • токен пользователя (My Profile → API Tokens) — проверяется через /user/tokens/verify;
  • токен аккаунта (cfat_…, Manage Account → API Tokens) — проверяется через
    /accounts/{account_id}/tokens/verify, поэтому для него нужен Account ID.
Для работы с DNS токену нужны права Zone → Zone → Read и Zone → DNS → Edit.
"""
from dataclasses import dataclass

import httpx

from app.core import integrations
from app.core.http import get_http

API = "https://api.cloudflare.com/client/v4"


class CloudflareError(Exception):
    pass


@dataclass
class DnsRecord:
    id: str
    name: str
    content: str
    proxied: bool
    ttl: int


class CloudflareClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or get_http()
        self.token = integrations.get("cloudflare_api_token").strip()
        self.account_id = integrations.get("cloudflare_account_id").strip()

    @property
    def is_account_token(self) -> bool:
        return self.token.startswith("cfat_") or bool(self.account_id)

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.token:
            raise CloudflareError("Cloudflare не настроен: укажите API Token в Настройках")
        try:
            resp = await self.client.request(
                method, f"{API}{path}", headers={"Authorization": f"Bearer {self.token}"}, **kwargs
            )
        except httpx.HTTPError as e:
            raise CloudflareError(f"Сетевая ошибка Cloudflare: {e}") from e
        try:
            data = resp.json()
        except ValueError as e:
            raise CloudflareError(f"Cloudflare вернул не JSON (HTTP {resp.status_code})") from e
        if not data.get("success"):
            errors = "; ".join(f"{x.get('code')}: {x.get('message')}" for x in data.get("errors", []))
            raise CloudflareError(f"Cloudflare HTTP {resp.status_code}: {errors or 'неизвестная ошибка'}")
        return data

    async def find_zone_id(self, domain: str) -> str:
        """Ищет зону, перебирая суффиксы: a.b.example.com → b.example.com → example.com."""
        parts = domain.strip(".").split(".")
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            params = {"name": candidate}
            if self.account_id:
                params["account.id"] = self.account_id
            data = await self._request("GET", "/zones", params=params)
            if data.get("result"):
                return data["result"][0]["id"]
        raise CloudflareError(
            f"Зона для {domain} не найдена. Проверьте, что домен в этом аккаунте Cloudflare и у токена есть "
            f"права Zone → Zone → Read и Zone → DNS → Edit для этой зоны"
        )

    async def get_a_records(self, zone_id: str, name: str) -> list[DnsRecord]:
        data = await self._request(
            "GET", f"/zones/{zone_id}/dns_records", params={"type": "A", "name": name, "per_page": 100}
        )
        return [
            DnsRecord(r["id"], r["name"], r["content"], bool(r.get("proxied")), int(r.get("ttl", 1)))
            for r in data.get("result", [])
        ]

    async def update_a_record(self, zone_id: str, record_id: str, ip: str) -> DnsRecord:
        # proxied=False — «серое облако»: трафик идёт напрямую на IP ноды
        data = await self._request(
            "PATCH", f"/zones/{zone_id}/dns_records/{record_id}", json={"content": ip, "proxied": False}
        )
        r = data["result"]
        return DnsRecord(r["id"], r["name"], r["content"], bool(r.get("proxied")), int(r.get("ttl", 1)))

    async def create_a_record(self, zone_id: str, name: str, ip: str) -> DnsRecord:
        data = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json={"type": "A", "name": name, "content": ip, "ttl": 60, "proxied": False},
        )
        r = data["result"]
        return DnsRecord(r["id"], r["name"], r["content"], bool(r.get("proxied")), int(r.get("ttl", 1)))

    async def _account_ids(self) -> list[str]:
        if self.account_id:
            return [self.account_id]
        try:
            data = await self._request("GET", "/accounts", params={"per_page": 50})
            return [a["id"] for a in data.get("result", []) if a.get("id")]
        except CloudflareError:
            return []

    async def verify_token(self) -> str:
        """Проверяет токен и права. Возвращает текст для панели."""
        verified = False
        errors: list[str] = []
        if not self.token.startswith("cfat_"):
            try:
                await self._request("GET", "/user/tokens/verify")
                verified = True
            except CloudflareError as e:
                errors.append(str(e))
        if not verified:
            ids = await self._account_ids()
            if not ids:
                raise CloudflareError(
                    "Это токен аккаунта (cfat_…) — укажите Account ID в настройках Cloudflare"
                    if self.token.startswith("cfat_") else (errors[0] if errors else "Токен не прошёл проверку")
                )
            for acc in ids:
                try:
                    await self._request("GET", f"/accounts/{acc}/tokens/verify")
                    verified = True
                    break
                except CloudflareError as e:
                    errors.append(str(e))
            if not verified:
                raise CloudflareError(errors[-1])

        # какие зоны видит токен (нужно право Zone:Read)
        params: dict = {"per_page": 50}
        if self.account_id:
            params["account.id"] = self.account_id
        zones = (await self._request("GET", "/zones", params=params)).get("result", [])
        if not zones:
            return ("Токен действителен, но не видит ни одной зоны — добавьте права "
                    "Zone → Zone → Read и Zone → DNS → Edit")
        names = ", ".join(z["name"] for z in zones[:5]) + (" …" if len(zones) > 5 else "")
        return f"Токен действителен, зон: {len(zones)} ({names})"
