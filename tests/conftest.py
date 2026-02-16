"""Shared pytest fixtures."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Generator

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token-123")
os.environ.setdefault("OPENAI_API_KEY", "test-key-456")
os.environ.setdefault("NOTION_TOKEN", "secret_test")
os.environ.setdefault("NOTION_DATABASE_ID", "test-db")
os.environ.setdefault("APP_ENV", "testing")

from src.models.journal_entry import (
    DailyRecord, DayRating, Goal, SleepInfo, TaskEntry, TestikStatus,
)
from src.utils.cache import CacheService


@pytest.fixture
def sample_records() -> list[DailyRecord]:
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
            journal_text=f"Woke up at 10:00. Sleep time 7:30. Recovery 80.\nPLUS TESTIK\nDay {i} notes.\nMARK: good",
        ))
    return records


@pytest.fixture
def burnout_records() -> list[DailyRecord]:
    records: list[DailyRecord] = []
    for i in range(7):
        records.append(DailyRecord(
            entry_date=date.today() - timedelta(days=6 - i),
            rating=DayRating.BAD if i < 5 else DayRating.VERY_BAD,
            testik=TestikStatus.MINUS_KATE if i < 3 else TestikStatus.MINUS,
            sleep=SleepInfo(sleep_hours=5.0 - i * 0.2),
            activities=["MARK", "CODING"],
            total_hours=11.0 + i * 0.5,
            tasks_count=2, tasks_completed=1,
            had_workout=False, had_coding=True,
            journal_text="MINUS TESTIK\nMARK: bad",
        ))
    return records


@pytest.fixture
def sample_tasks() -> list[TaskEntry]:
    return [
        TaskEntry(id="t1", title="MARK", entry_date=date(2026, 2, 15),
                  tags=["MARK"], checkbox=True,
                  body_text="Woke up at 12:30. Sleep time 8:54. Recovery 81\nMINUS TESTIK KATE\nMARK: good"),
        TaskEntry(id="t2", title="GYM", entry_date=date(2026, 2, 15),
                  tags=["GYM"], checkbox=True, hours=1.5),
        TaskEntry(id="t3", title="CODING", entry_date=date(2026, 2, 15),
                  tags=["CODING"], checkbox=True, hours=3.0),
    ]


@pytest.fixture
def sample_goals() -> list[Goal]:
    return [
        Goal(id="g1", user_id=123, name="GYM", target_activity="GYM", target_count=4, period="week"),
        Goal(id="g2", user_id=123, name="CODING", target_activity="CODING", target_count=5, period="week"),
        Goal(id="g3", user_id=123, name="TESTIK_PLUS", target_activity="TESTIK_PLUS", target_count=5, period="week"),
    ]


@pytest.fixture
def cache_service(tmp_path) -> Generator[CacheService, None, None]:
    import src.utils.cache as cache_module
    original = cache_module.DB_PATH
    cache_module.DB_PATH = tmp_path / "test_cache.db"
    svc = CacheService(ttl_seconds=60)
    yield svc
    cache_module.DB_PATH = original


@pytest.fixture
def mock_notion_response() -> list[dict]:
    return [
        {"id": "p1", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "MARK"}]},
            "Date": {"date": {"start": "2026-02-15"}},
            "Tags": {"multi_select": [{"name": "MARK"}]},
            "Checkbox": {"checkbox": True},
            "It took (hours)": {"number": None},
        }},
        {"id": "p2", "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "GYM"}]},
            "Date": {"date": {"start": "2026-02-15"}},
            "Tags": {"multi_select": [{"name": "GYM"}]},
            "Checkbox": {"checkbox": True},
            "It took (hours)": {"number": 1.5},
        }},
    ]
