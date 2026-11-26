"""Проверка IP всеми включёнными источниками и объединение результатов."""
import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.checkers import CheckResult, all_checkers
from app.core.http import get_http


def decide(results: list[CheckResult]) -> bool | None:
    """Итог по нескольким источникам — большинством голосов ответивших.

    Источники иногда ошибаются (например, один видит «бан», а сервер на деле работает),
    поэтому один голос «бан» против двух «доступен» баном не считается.
    Ничья — решает первый ответивший источник по порядку (Red Atlas, затем Latency Lab, bschekbot).
    None — никто не ответил.
    """
    answered = [r for r in results if r.blocked is not None]
    if not answered:
        return None
    banned = sum(1 for r in answered if r.blocked)
    clean = len(answered) - banned
    if banned != clean:
        return banned > clean
    return bool(answered[0].blocked)


@dataclass
class AggregatedResult:
    ip: str
    # итог большинством ответивших источников (см. decide); None — никто не ответил
    blocked: bool | None
    results: list[CheckResult] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        return [f"{r.checker}: {r.error}" for r in self.results if r.error]

    def to_details(self) -> dict:
        return {
            r.checker: {"blocked": r.blocked, "error": r.error, **r.details}
            for r in self.results
        }


async def check_ip(
    ip: str, checker_names: list[str], port: int | None = None, options: dict[str, Any] | None = None
) -> AggregatedResult:
    registry = all_checkers()
    order = list(registry)  # порядок источников: Red Atlas, Latency Lab, bschekbot
    names = sorted((n for n in dict.fromkeys(checker_names) if n in registry), key=order.index)
    instances = [registry[n](get_http(), options) for n in names]
    if not instances:
        return AggregatedResult(ip, None, [CheckResult("none", None, error="Нет включённых источников проверки")])

    results = await asyncio.gather(*(c.check(ip, port) for c in instances))
    return AggregatedResult(ip, decide(list(results)), list(results))


class IPCheckCache:
    """Кэш на один цикл: один IP проверяется один раз, даже если он в нескольких доменах."""

    def __init__(self, options: dict[str, Any]):
        self.options = options
        self.checker_names: list[str] = options["enabled_checkers"]
        self.default_port = int(options.get("tcp_check_port") or 443)
        self.delay = max(int(options.get("checker_delay_ms") or 0), 0) / 1000
        self._cache: dict[tuple[str, int, tuple[str, ...]], AggregatedResult] = {}
        self._first = True

    async def get(self, ip: str, port: int | None = None, checkers: list[str] | None = None) -> AggregatedResult:
        """checkers — свои источники для этого IP (выбраны на странице домена); None — общие."""
        names = list(checkers) if checkers else list(self.checker_names)
        port = port or self.default_port
        key = (ip, port, tuple(sorted(names)))
        if key in self._cache:
            return self._cache[key]
        if not self._first and self.delay:
            await asyncio.sleep(self.delay)
        self._first = False
        res = await check_ip(ip, names, port, self.options)
        self._cache[key] = res
        return res


def aggregate_stored(ip: str, details: dict, names: list[str]) -> AggregatedResult | None:
    """Итог по уже сохранённым ответам выбранных источников — без новых запросов.

    None — если по выбранным источникам ещё нет ответов.
    """
    order = list(all_checkers())
    results = [
        CheckResult(n, details[n].get("blocked"), error=details[n].get("error"))
        for n in sorted(names, key=lambda x: order.index(x) if x in order else len(order))
        if isinstance(details.get(n), dict)
    ]
    if not results:
        return None
    return AggregatedResult(ip, decide(results), results)
