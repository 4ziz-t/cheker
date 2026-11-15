"""Базовый интерфейс источника проверки IP.

Чтобы добавить новый источник:
  1. создайте файл в app/checkers/, унаследуйте класс от BaseChecker;
  2. повесьте на класс декоратор @register_checker;
  3. импортируйте модуль в app/checkers/__init__.py.
После этого источник появится во фронте (Настройки → Источники проверки).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class CheckResult:
    checker: str
    # True — заблокирован, False — чист, None — проверить не удалось
    blocked: bool | None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class BaseChecker(ABC):
    #: уникальный идентификатор (используется в настройках)
    name: str = ""
    #: человекочитаемое название для фронта
    title: str = ""
    description: str = ""
    #: включён ли источник по умолчанию при первом запуске
    enabled_by_default: bool = False

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @abstractmethod
    async def check(self, ip: str) -> CheckResult:
        """Проверить один IPv4-адрес."""
