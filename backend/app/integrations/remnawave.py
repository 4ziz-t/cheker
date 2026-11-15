"""Клиент API панели Remnawave."""
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.http import get_http


class RemnawaveError(Exception):
    pass


@dataclass
class RemnaNode:
    uuid: str
    name: str
    address: str
    port: int | None
    country_code: str
    is_connected: bool
    is_disabled: bool
    is_connecting: bool
    users_online: int | None
    xray_version: str | None
    last_status_message: str | None

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "RemnaNode":
        return cls(
            uuid=d["uuid"],
            name=d.get("name") or "",
            address=d.get("address") or "",
            port=d.get("port"),
            country_code=d.get("countryCode") or "",
            is_connected=bool(d.get("isConnected")),
            is_disabled=bool(d.get("isDisabled")),
            is_connecting=bool(d.get("isConnecting")),
            users_online=d.get("usersOnline"),
            xray_version=d.get("xrayVersion"),
            last_status_message=d.get("lastStatusMessage"),
        )


class RemnawaveClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        s = get_settings()
        self.client = client or get_http()
        self.base = s.remnawave_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {s.remnawave_token}",
            # панель отклоняет запросы по http без этих заголовков
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "127.0.0.1",
        }
        if s.remnawave_api_key:
            self.headers["X-Api-Key"] = s.remnawave_api_key

    async def _request(self, method: str, path: str) -> Any:
        if not self.base:
            raise RemnawaveError("REMNAWAVE_URL / REMNAWAVE_TOKEN не заданы в .env")
        try:
            resp = await self.client.request(method, f"{self.base}{path}", headers=self.headers)
        except httpx.HTTPError as e:
            raise RemnawaveError(f"Сетевая ошибка Remnawave: {e}") from e
        if resp.status_code >= 400:
            msg = resp.text[:300]
            try:
                msg = resp.json().get("message", msg)
            except ValueError:
                pass
            raise RemnawaveError(f"Remnawave HTTP {resp.status_code}: {msg}")
        try:
            data = resp.json()
        except ValueError as e:
            raise RemnawaveError("Remnawave вернул не JSON") from e
        return data.get("response", data)

    async def get_nodes(self) -> list[RemnaNode]:
        data = await self._request("GET", "/api/nodes")
        if isinstance(data, dict):  # на случай обёртки вида {"nodes": [...]}
            data = data.get("nodes", [])
        return [RemnaNode.from_api(n) for n in data]

    async def restart_node(self, uuid: str) -> None:
        await self._request("POST", f"/api/nodes/{uuid}/actions/restart")

    async def enable_node(self, uuid: str) -> None:
        await self._request("POST", f"/api/nodes/{uuid}/actions/enable")

    async def disable_node(self, uuid: str) -> None:
        await self._request("POST", f"/api/nodes/{uuid}/actions/disable")
