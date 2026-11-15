"""Источники проверки IP. Импортируйте здесь каждый новый модуль-чекер."""
# порядок импорта = порядок в интерфейсе (первым — основной источник)
from app.checkers import latencylab, cheburcheck, cheburcheck_probe, geopinger  # noqa: F401, I001
from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import all_checkers, default_enabled, register_checker

__all__ = ["BaseChecker", "CheckResult", "all_checkers", "default_enabled", "register_checker"]
