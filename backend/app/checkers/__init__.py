"""Источники проверки IP. Импортируйте здесь каждый новый модуль-чекер."""
# Каждый новый источник импортируйте здесь (порядок = порядок в интерфейсе)
from app.checkers import latencylab, bschek  # noqa: F401, I001
from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import all_checkers, default_enabled, register_checker

__all__ = ["BaseChecker", "CheckResult", "all_checkers", "default_enabled", "register_checker"]
