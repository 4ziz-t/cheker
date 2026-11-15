from app.checkers.base import BaseChecker

_REGISTRY: dict[str, type[BaseChecker]] = {}


def register_checker(cls: type[BaseChecker]) -> type[BaseChecker]:
    if not cls.name:
        raise ValueError(f"{cls.__name__}: не задан name")
    if cls.name in _REGISTRY:
        raise ValueError(f"Чекер '{cls.name}' уже зарегистрирован")
    _REGISTRY[cls.name] = cls
    return cls


def all_checkers() -> dict[str, type[BaseChecker]]:
    return dict(_REGISTRY)


def default_enabled() -> list[str]:
    return [name for name, cls in _REGISTRY.items() if cls.enabled_by_default]
