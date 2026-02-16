"""Shared pytest fixtures for all test modules."""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Generator

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-123")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-456")
os.environ.setdefault("NOTION_TOKEN", "secret_test_notion_token")
os.environ.setdefault("NOTION_DATABASE_ID", "test-db-id-789")
os.environ.setdefault("APP_ENV", "testing")

from src.models.journal_entry import (
    DailyRecord,
    DayRating,
    SleepInfo,
    TaskEntry,
    TestikStatus,
)
from src.utils.cache import CacheService


@pytest.fixture
def sample_records() -> list[DailyRecord]:
    """Generate 14 days of sample daily records."""
    ratings = [
        DayRating.PERFECT, DayRating.GOOD, DayRating.GOOD, DayRating.NORMAL,
        DayRating.NORMAL, DayRating.BAD, DayRating.GOOD, DayRating.PERFECT,
        DayRating.NORMAL, DayRating.GOOD, DayRating.BAD, DayRating.VERY_BAD,
        DayRating.NORMAL, DayRating.VERY_GOOD,
    ]
    testiks = [
        TestikStatus.PLUS, TestikStatus.PLUS, TestikStatus.MINUS_KATE,
        TestikStatus.PLUS, TestikStatus.MINUS, TestikStatus.MINUS_KATE,
        TestikStatus.PLUS, TestikStatus.PLUS, TestikStatus.MINUS,
        TestikStatus.PLUS, TestikStatus.MINUS_KATE, TestikStatus.MINUS,
        TestikStatus.PLUS, TestikStatus.PLUS,
    ]
    records: list[DailyRecord] = []
    for i in range(14):
        records.append(DailyRecord(
            entry_date=date.today() - timedelta(days=13 - i),
            rating=ratings[i],
            testik=testiks[i],
            sleep=SleepInfo(sleep_hours=5.5 + (i % 4) * 0.5, woke_up_at="10:00"),
            activities=["MARK", "CODING", "GYM"] if i % 2 == 0 else ["MARK", "AI", "UNIVERSITY"],
            total_hours=6.0 + (i % 5),
            tasks_count=3 + (i % 4),
            tasks_completed=2 + (i % 3),
            had_workout=i % 2 == 0,
            had_university=i % 3 == 0,
            had_coding=i % 2 == 0,
            had_kate=i % 5 == 0,
            journal_text=f"Woke up at 10:00. Sleep time 7:30. Recovery 80.\nDay {i} notes.",
        ))
    return records


@pytest.fixture
def burnout_records() -> list[DailyRecord]:
    """Records that should trigger high burnout risk."""
    records: list[DailyRecord] = []
    for i in range(7):
        records.append(DailyRecord(
            entry_date=date.today() - timedelta(days=6 - i),
            rating=DayRating.BAD if i < 5 else DayRating.VERY_BAD,
            testik=TestikStatus.MINUS_KATE if i < 3 else TestikStatus.MINUS,
            sleep=SleepInfo(sleep_hours=5.0 - i * 0.2),
            activities=["MARK", "CODING"],
            total_hours=11.0 + i * 0.5,
            tasks_count=2,
            tasks_completed=1,
            had_workout=False,
            had_university=False,
            had_coding=True,
            had_kate=False,
            journal_text="MINUS TESTIK\nMARK: bad",
        ))
    return records


@pytest.fixture
def sample_tasks() -> list[TaskEntry]:
    """Sample task entries for testing."""
    return [
        TaskEntry(
            id="task-001", title="MARK",
            entry_date=date(2026, 2, 15),
            tags=["MARK"], checkbox=True, hours=None,
            body_text="Woke up at 12:30. Sleep time 8:54. Recovery 81 by Apple Watch\nMINUS TESTIK KATE\nMARK: good",
        ),
        TaskEntry(
            id="task-002", title="GYM",
            entry_date=date(2026, 2, 15),
            tags=["GYM"], checkbox=True, hours=1.5,
            body_text="",
        ),
        TaskEntry(
            id="task-003", title="CODING",
            entry_date=date(2026, 2, 15),
            tags=["CODING"], checkbox=True, hours=3.0,
            body_text="",
        ),
    ]


@pytest.fixture
def cache_service(tmp_path) -> Generator[CacheService, None, None]:
    import src.utils.cache as cache_module
    original_path = cache_module.DB_PATH
    cache_module.DB_PATH = tmp_path / "test_cache.db"
    svc = CacheService(ttl_seconds=60)
    yield svc
    cache_module.DB_PATH = original_path


@pytest.fixture
def mock_notion_response() -> list[dict]:
    """Sample Notion API response pages matching Tasks DB structure."""
    return [
        {
            "id": "page-001",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "MARK"}]},
                "Date": {"date": {"start": "2026-02-15"}},
                "Tags": {"multi_select": [{"name": "MARK"}]},
                "Checkbox": {"checkbox": True},
                "It took (hours)": {"number": None},
            },
        },
        {
            "id": "page-002",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "GYM"}]},
                "Date": {"date": {"start": "2026-02-15"}},
                "Tags": {"multi_select": [{"name": "GYM"}]},
                "Checkbox": {"checkbox": True},
                "It took (hours)": {"number": 1.5},
            },
        },
        {
            "id": "page-003",
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "CODING"}]},
                "Date": {"date": {"start": "2026-02-15"}},
                "Tags": {"multi_select": [{"name": "CODING"}]},
                "Checkbox": {"checkbox": True},
                "It took (hours)": {"number": 3.0},
            },
        },
    ]
