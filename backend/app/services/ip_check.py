"""Проверка IP всеми включёнными источниками и объединение результатов."""
import asyncio
from dataclasses import dataclass, field

from app.checkers import CheckResult, all_checkers
from app.core.http import get_http


@dataclass
class AggregatedResult:
    ip: str
    # True — хотя бы один источник видит бан; False — все ответившие чисты; None — никто не ответил
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


async def check_ip(ip: str, checker_names: list[str]) -> AggregatedResult:
    registry = all_checkers()
    instances = [registry[n](get_http()) for n in checker_names if n in registry]
    if not instances:
        return AggregatedResult(ip, None, [CheckResult("none", None, error="Нет включённых источников проверки")])

    results = await asyncio.gather(*(c.check(ip) for c in instances))
    answered = [r for r in results if r.blocked is not None]
    if any(r.blocked for r in answered):
        blocked: bool | None = True
    elif answered:
        blocked = False
    else:
        blocked = None
    return AggregatedResult(ip, blocked, list(results))


class IPCheckCache:
    """Кэш на один цикл: один IP проверяется один раз, даже если он в нескольких доменах."""

    def __init__(self, checker_names: list[str], delay_ms: int):
        self.checker_names = checker_names
        self.delay = max(delay_ms, 0) / 1000
        self._cache: dict[str, AggregatedResult] = {}
        self._first = True

    async def get(self, ip: str) -> AggregatedResult:
        if ip in self._cache:
            return self._cache[ip]
        if not self._first and self.delay:
            await asyncio.sleep(self.delay)
        self._first = False
        res = await check_ip(ip, self.checker_names)
        self._cache[ip] = res
        return res
