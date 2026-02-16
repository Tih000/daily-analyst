"""Application configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _list_from_env(key: str) -> list[int]:
    """Parse comma-separated list of integers from env variable."""
    raw = os.getenv(key, "")
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = field(default_factory=lambda: os.environ["TELEGRAM_BOT_TOKEN"])
    webhook_url: str = field(default_factory=lambda: os.getenv("TELEGRAM_WEBHOOK_URL", ""))
    allowed_user_ids: list[int] = field(default_factory=lambda: _list_from_env("ALLOWED_USER_IDS"))


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str = field(default_factory=lambda: os.environ["OPENAI_API_KEY"])
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


@dataclass(frozen=True)
class NotionConfig:
    token: str = field(default_factory=lambda: os.environ["NOTION_TOKEN"])
    database_id: str = field(default_factory=lambda: os.environ["NOTION_DATABASE_ID"])


@dataclass(frozen=True)
class GoogleSheetsConfig:
    credentials_json: Optional[dict] = field(default_factory=lambda: _parse_google_creds())
    sheet_id: str = field(default_factory=lambda: os.getenv("GOOGLE_SHEET_ID", ""))

    @property
    def enabled(self) -> bool:
        return self.credentials_json is not None and bool(self.sheet_id)


def _parse_google_creds() -> Optional[dict]:
    raw = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
    if not raw or raw == "{}":
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@dataclass(frozen=True)
class AppConfig:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "300"))
    )

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@dataclass(frozen=True)
class Settings:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    notion: NotionConfig = field(default_factory=NotionConfig)
    google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)
    app: AppConfig = field(default_factory=AppConfig)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance, cached after first call."""
    return Settings()
