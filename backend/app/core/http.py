"""Общий HTTP-клиент (создаётся при старте приложения)."""
import httpx

from app.core.config import get_settings

_client: httpx.AsyncClient | None = None


def get_http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=get_settings().http_timeout,
            headers={"User-Agent": "cheker/1.0"},
            follow_redirects=True,
        )
    return _client


async def close_http() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
