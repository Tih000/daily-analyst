"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _frozenset_from_env(key: str) -> frozenset[int]:
    """Parse comma-separated list of integers from env variable into a frozenset."""
    raw = os.getenv(key, "")
    if not raw:
        return frozenset()
    return frozenset(int(x.strip()) for x in raw.split(",") if x.strip())


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = field(default_factory=lambda: os.environ["TELEGRAM_BOT_TOKEN"])
    webhook_url: str = field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_URL", ""))
    webhook_secret: str = field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_SECRET", ""))
    allowed_user_ids: frozenset[int] = field(
        default_factory=lambda: _frozenset_from_env("ALLOWED_USER_IDS")
    )


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str = field(default_factory=lambda: os.environ["OPENAI_API_KEY"])
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


@dataclass(frozen=True)
class NotionConfig:
    token: str = field(default_factory=lambda: os.environ["NOTION_TOKEN"])
    database_id: str = field(default_factory=lambda: os.environ["NOTION_DATABASE_ID"])


@dataclass(frozen=True)
class AppConfig:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    )

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@dataclass(frozen=True)
class Settings:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    notion: NotionConfig = field(default_factory=NotionConfig)
    app: AppConfig = field(default_factory=AppConfig)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance, cached after first call."""
    return Settings()
