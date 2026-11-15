"""Запуск фоновых задач с удержанием ссылки (чтобы их не собрал GC)."""
import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _tasks.discard(t)
        if not t.cancelled() and t.exception():
            log.error("Фоновая задача упала", exc_info=t.exception())

    task.add_done_callback(_done)
    return task
