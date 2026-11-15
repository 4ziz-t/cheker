"""Источники проверки IP. Импортируйте здесь каждый новый модуль-чекер."""
from app.checkers import cheburcheck, cheburcheck_probe, geopinger  # noqa: F401
from app.checkers.base import BaseChecker, CheckResult
from app.checkers.registry import all_checkers, default_enabled, register_checker

__all__ = ["BaseChecker", "CheckResult", "all_checkers", "default_enabled", "register_checker"]
