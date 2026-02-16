"""Shared pytest fixtures for all test modules."""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set test env before importing app modules
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-123")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-456")
os.environ.setdefault("NOTION_TOKEN", "secret_test_notion_token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-db-id-789")
os.environ.setdefault("APP_ENV", "testing")

from src.models.journal_entry import JournalEntry, Mood, Testik
from src.utils.cache import CacheService, DB_PATH


@pytest.fixture
def sample_entries() -> list[JournalEntry]:
    """Generate 14 days of sample journal entries for testing."""
    entries: list[JournalEntry] = []
    moods = [Mood.PERFECT, Mood.GOOD, Mood.GOOD, Mood.NORMAL, Mood.NORMAL,
             Mood.BAD, Mood.GOOD, Mood.PERFECT, Mood.NORMAL, Mood.GOOD,
             Mood.BAD, Mood.VERY_BAD, Mood.NORMAL, Mood.GOOD]
    testiks = [Testik.PLUS, Testik.PLUS, Testik.MINUS_KATE, Testik.PLUS,
               Testik.MINUS_SOLO, Testik.MINUS_KATE, Testik.PLUS, Testik.PLUS,
               Testik.MINUS_SOLO, Testik.PLUS, Testik.MINUS_KATE, Testik.MINUS_KATE,
               Testik.PLUS, Testik.PLUS]

    for i in range(14):
        entries.append(JournalEntry(
            id=f"page-{i:03d}",
            entry_date=date.today() - timedelta(days=13 - i),
            mood=moods[i],
            hours_worked=6.0 + (i % 5),
            tasks_completed=3 + (i % 4),
            testik=testiks[i],
            workout=i % 3 == 0,
            university=i % 4 == 0,
            earnings_usd=50.0 * (i % 3),
            sleep_hours=5.5 + (i % 4) * 0.5,
            notes=f"Test note for day {i}",
        ))
    return entries


@pytest.fixture
def burnout_entries() -> list[JournalEntry]:
    """Entries that should trigger high burnout risk."""
    entries: list[JournalEntry] = []
    for i in range(7):
        entries.append(JournalEntry(
            id=f"burn-{i:03d}",
            entry_date=date.today() - timedelta(days=6 - i),
            mood=Mood.BAD if i < 5 else Mood.VERY_BAD,
            hours_worked=11.0 + i * 0.5,
            tasks_completed=2,
            testik=Testik.MINUS_KATE if i < 4 else Testik.MINUS_SOLO,
            workout=False,
            university=False,
            earnings_usd=0,
            sleep_hours=5.0 - i * 0.2,
            notes="Burnout test",
        ))
    return entries


@pytest.fixture
def cache_service(tmp_path) -> Generator[CacheService, None, None]:
    """Provide a CacheService backed by a temp database."""
    import src.utils.cache as cache_module
    original_path = cache_module.DB_PATH
    cache_module.DB_PATH = tmp_path / "test_cache.db"
    svc = CacheService(ttl_seconds=60)
    yield svc
    cache_module.DB_PATH = original_path


@pytest.fixture
def mock_notion_response() -> list[dict]:
    """Sample Notion API response pages."""
    return [
        {
            "id": "page-001",
            "properties": {
                "Date": {"date": {"start": "2025-01-15"}},
                "Mood": {"select": {"name": "GOOD"}},
                "Hours Worked": {"number": 7.5},
                "Tasks Completed": {"number": 5},
                "TESTIK": {"select": {"name": "PLUS"}},
                "Workout": {"checkbox": True},
                "University": {"checkbox": False},
                "Earnings USD": {"number": 100},
                "Sleep Hours": {"number": 7.5},
                "Notes": {"rich_text": [{"plain_text": "Great day!"}]},
            },
        },
        {
            "id": "page-002",
            "properties": {
                "Date": {"date": {"start": "2025-01-16"}},
                "Mood": {"select": {"name": "BAD"}},
                "Hours Worked": {"number": 4},
                "Tasks Completed": {"number": 2},
                "TESTIK": {"select": {"name": "MINUS_KATE"}},
                "Workout": {"checkbox": False},
                "University": {"checkbox": True},
                "Earnings USD": {"number": 0},
                "Sleep Hours": {"number": 5},
                "Notes": {"rich_text": [{"plain_text": "Rough day."}]},
            },
        },
    ]
