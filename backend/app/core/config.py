"""Конфигурация приложения из переменных окружения (.env)."""
import re
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Доступ к панели ---
    app_password: str
    session_ttl_days: int = 7
    cookie_secure: bool = True
    login_max_attempts: int = 5          # неудачных попыток с одного IP
    login_window_minutes: int = 15       # окно подсчёта попыток
    login_lock_minutes: int = 15         # блокировка IP
    login_global_max_failures: int = 30  # всего неудачных попыток за час (защита от подбора с разных IP)
    login_global_lock_minutes: int = 30

    # --- Хранилище ---
    database_url: str = "sqlite+aiosqlite:///./data/cheker.db"

    # --- Часовой пояс для сводки и отображения ---
    tz: str = "Europe/Moscow"

    # --- Remnawave ---
    remnawave_url: str = ""
    remnawave_token: str = ""
    remnawave_api_key: str = ""   # X-Api-Key, если панель за Caddy с доп. защитой (необязательно)

    # --- Cloudflare ---
    cloudflare_api_token: str = ""

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_api_url: str = "https://api.telegram.org"

    # --- Чекеры ---
    cheburcheck_url: str = "https://cheburcheck.ru/api/v1"

    # --- Прочее ---
    http_timeout: float = 20.0
    log_level: str = "INFO"

    @field_validator("app_password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9]{4,6}", v or ""):
            raise ValueError("APP_PASSWORD должен состоять из 4–6 латинских букв или цифр")
        return v

    @property
    def remnawave_configured(self) -> bool:
        return bool(self.remnawave_url and self.remnawave_token)

    @property
    def cloudflare_configured(self) -> bool:
        return bool(self.cloudflare_api_token)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
