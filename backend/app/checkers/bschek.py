"""Дополнительный источник: bschekbot (bsbord.com) — TCP до IP:порт с мобильных операторов РФ.

API: POST https://bsbord.com/v1/probe (синхронно), заголовок Idempotency-Key.
Проверка идёт через «единицы» оператор × округ × Белый список (op_key "mts|цфо|off").
Каждая единица — отдельное списание (1 кредит = 1 копейка), поэтому набор единиц задаётся в настройках.

Для поиска бана ТСПУ по умолчанию берутся единицы БЕЗ Белого списка (dpi "off"): с включённым
Белым списком оператор режет почти всё, и любой зарубежный IP выглядел бы «забаненным».

Вердикт: доля единиц, с которых порт недоступен (tcp.ok = false), ≥ порога → бан.
"""
import asyncio
import time
import uuid
from typing import Any

import httpx

from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import register_checker
from app.core import integrations
from app.core.config import get_settings

OPERATOR_NAMES = {
    "mts": "МТС", "beeline": "Билайн", "megafon": "МегаФон", "tele2": "T2", "t2": "T2",
    "yota": "Yota", "t-mobile": "Т-Мобайл", "tmobile": "Т-Мобайл", "sberm": "СберМобайл", "rtk": "Ростелеком",
}
MAX_WAIT = 300.0          # сколько всего ждём результат одной проверки
_lock = asyncio.Lock()    # лимиты у bsbord на аккаунт — шлём по одному


def derive_dpi(units: list[str], fallback: str) -> str:
    """Режим Белого списка по самим ключам: если у каждого ключа явно указано on/off —
    берём их (оба → any). Иначе — значение из настроек."""
    states = set()
    for key in units:
        parts = key.split("|")
        state = parts[2].strip().lower() if len(parts) == 3 else ""
        if state not in ("on", "off"):
            return fallback
        states.add(state)
    if not states:
        return fallback
    return states.pop() if len(states) == 1 else "any"


class BschekError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(f"HTTP {status} {code}: {message}")
        self.status, self.code, self.details = status, code, details or {}

    @property
    def retryable(self) -> bool:
        return bool(self.details.get("retryable"))


@register_checker
class BschekChecker(BaseChecker):
    name = "bschek"
    title = "bschekbot (bsbord)"
    description = (
        "Дополнительный источник: TCP до IP:порт через мобильных операторов РФ (единица = оператор × округ × "
        "Белый список). Платно: каждая единица — отдельное списание"
    )
    enabled_by_default = False

    @property
    def _base(self) -> str:
        return get_settings().bschek_url.rstrip("/")

    def _headers(self, idem: str | None = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {integrations.get('bschek_token')}"}
        if idem:
            h["Idempotency-Key"] = idem
        return h

    async def _request(self, method: str, path: str, *, idem: str | None = None, **kwargs) -> dict[str, Any]:
        try:
            resp = await self.client.request(
                method, f"{self._base}{path}", headers=self._headers(idem), timeout=120, **kwargs
            )
        except httpx.TimeoutException as e:
            raise BschekError(0, "timeout", "ответ не получен вовремя", {"retryable": True}) from e
        except httpx.HTTPError as e:
            raise BschekError(0, "network", f"{e.__class__.__name__}: {e}", {"retryable": True}) from e

        if resp.status_code == 524:  # фронт оборвал долгую синхронную пробу — она идёт дальше
            raise BschekError(524, "timeout_524", "проба ещё идёт", {"retryable": True})
        try:
            data = resp.json()
        except ValueError as e:
            raise BschekError(resp.status_code, "bad_response", "ответ не JSON") from e
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error") or {}
            raise BschekError(resp.status_code, err.get("code", "error"), err.get("message", ""),
                              err.get("details") or {})
        return data

    async def units(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/operators")
        return data.get("units") or []

    async def _probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /probe с одним Idempotency-Key: повтор того же запроса не спишет второй раз."""
        idem = str(uuid.uuid4())
        deadline = time.monotonic() + MAX_WAIT
        while True:
            try:
                return await self._request("POST", "/probe", idem=idem, json=payload)
            except BschekError as e:
                in_progress = e.code in ("request_in_progress", "timeout_524", "timeout")
                transient = e.retryable or e.code in ("rate_limited", "too_many_active", "busy")
                if (in_progress or transient) and time.monotonic() < deadline:
                    # ждём и повторяем С ТЕМ ЖЕ ключом — получим результат той же пробы
                    await asyncio.sleep(float(e.details.get("retry_after") or 10))
                    continue
                raise

    async def check(self, ip: str, port: int | None = None) -> CheckResult:
        if not integrations.get("bschek_token"):
            return CheckResult(self.name, None, error="Не задан API-ключ bschekbot (Настройки → Интеграции)")
        port = int(port or self.options.get("tcp_check_port") or 443)
        units = list(self.options.get("bschek_units") or [])
        if not units:
            # ничего не выбрано — не проверяем и ничего не списываем
            return CheckResult(self.name, None, error="Не выбраны операторы (Настройки → Источники → bschekbot)")
        dpi = derive_dpi(units, self.options.get("bschek_dpi") or "off")
        fail_ratio = float(self.options.get("bschek_fail_percent", 50)) / 100

        payload = {
            "target": f"{ip}:{port}",
            "operators": units,
            "probes": {"tcp": True},  # строгий селектор: только TCP, ICMP не нужен и не оплачивается
            "dpi": dpi,
        }
        async with _lock:
            try:
                data = await self._probe(payload)
            except BschekError as e:
                return CheckResult(self.name, None, error=str(e))

        by_target = data.get("by_target") or {}
        legs = next(iter(by_target.values()), {}).get("by_operator") or {}
        ok_units, fail_units, units_list = [], [], []
        for op_key, leg in legs.items():
            code = leg.get("operator") or op_key.split("|")[0]
            name = OPERATOR_NAMES.get(code, code)
            label = f"{name} {leg.get('region', '')}".strip()
            tcp = leg.get("tcp") or {}
            reachable = None
            if leg.get("ok") and not leg.get("dns_fail"):  # проба выполнена
                reachable = tcp.get("ok") if isinstance(tcp.get("ok"), bool) else (leg.get("icmp") or {}).get("ok")
            units_list.append({
                "op_key": op_key,
                "name": name,
                "region": leg.get("region"),
                "dpi": leg.get("dpi"),
                "reachable": reachable if isinstance(reachable, bool) else None,
                "tcp": f"{tcp.get('received', '?')}/{tcp.get('total', '?')}" if tcp else None,
                "error": leg.get("error") or tcp.get("error"),
            })
            if isinstance(reachable, bool):
                (ok_units if reachable else fail_units).append(label)

        details = {
            "port": port,
            "units_ok": ok_units,
            "units_fail": fail_units,
            "units": units_list,
            "cost_credits": data.get("cost_credits"),
        }
        total = len(ok_units) + len(fail_units)
        if total == 0:
            skipped = len(data.get("skipped_unavailable") or []) + len(data.get("skipped_dpi_off") or [])
            return CheckResult(self.name, None, details=details,
                               error=f"Ни одна единица не дала результат (пропущено: {skipped})")
        return CheckResult(self.name, len(fail_units) / total >= fail_ratio, details=details)

    async def status(self) -> str | None:
        if not integrations.get("bschek_token"):
            return "Ключ не задан (Настройки → Интеграции)"
        try:
            acc = await self._request("GET", "/account")
        except BschekError as e:
            return f"Ошибка: {e}"
        total = acc.get("balance_total")
        rub = f"{total / 100:.2f} ₽" if isinstance(total, (int, float)) else "?"
        return f"Баланс: {rub}, тариф: {acc.get('tier', '?')}"
