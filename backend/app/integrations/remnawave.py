"""Клиент API панели Remnawave — ТОЛЬКО ЧТЕНИЕ.

Cheker ничего не меняет в Remnawave: клиент умеет делать только GET-запросы
(список нод и статистика скорости). Любой другой метод запрещён в _request.
"""
from dataclasses import dataclass
from typing import Any

import httpx

from app.core import integrations
from app.core.http import get_http


class RemnawaveError(Exception):
    pass


def _to_int(v: Any) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


# эндпоинты «скорости в реальном времени» в разных версиях панели
REALTIME_PATHS = ("/api/bandwidth-stats/nodes/realtime", "/api/nodes/usage/realtime")


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
    traffic_used_bytes: int | None = None

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
            traffic_used_bytes=_to_int(d.get("trafficUsedBytes")),
        )


class RemnawaveClient:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client or get_http()
        self.base = integrations.get("remnawave_url").rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {integrations.get('remnawave_token')}",
            # панель отклоняет запросы по http без этих заголовков
            "X-Forwarded-Proto": "https",
            "X-Forwarded-For": "127.0.0.1",
        }
        api_key = integrations.get("remnawave_api_key")
        if api_key:
            self.headers["X-Api-Key"] = api_key

    async def _request(self, method: str, path: str) -> Any:
        if method.upper() != "GET":
            raise RemnawaveError("Cheker работает с Remnawave только на чтение")
        if not self.base or not integrations.get("remnawave_token"):
            raise RemnawaveError("Remnawave не настроен: укажите URL и токен в Настройках")
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
            data = data.get("nodes")
        if not isinstance(data, list):
            raise RemnawaveError("Remnawave вернул неожиданный ответ на список нод")
        try:
            return [RemnaNode.from_api(n) for n in data if isinstance(n, dict)]
        except KeyError as e:
            raise RemnawaveError(f"В ответе Remnawave у ноды нет поля {e}") from e

    async def get_realtime_speeds(self) -> dict[str, int] | None:
        """Скорость нод (байт/с) из realtime-статистики панели.

        Возвращает {uuid: bytes_per_sec} или None, если ни один эндпоинт не поддерживается
        (тогда скорость считается по приросту trafficUsedBytes).
        """
        for path in REALTIME_PATHS:
            try:
                data = await self._request("GET", path)
            except RemnawaveError:
                continue
            items = data if isinstance(data, list) else (data or {}).get("nodes") or []
            speeds: dict[str, int] = {}
            for it in items:
                if not isinstance(it, dict):
                    continue
                uuid = it.get("nodeUuid") or it.get("uuid")
                total = _to_int(it.get("totalSpeedBps"))
                if total is None:
                    down, up = _to_int(it.get("downloadSpeedBps")), _to_int(it.get("uploadSpeedBps"))
                    total = (down or 0) + (up or 0) if (down is not None or up is not None) else None
                if uuid and total is not None:
                    speeds[uuid] = total
            if speeds:
                return speeds
        return None
